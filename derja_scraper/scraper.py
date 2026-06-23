from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from derja_scraper.audio import trim_audio_clip
from derja_scraper.parser import parse_search_results


SEARCH_URL = "https://derja.ninja/search"


@dataclass(frozen=True)
class ScrapeProgress:
    completed: int
    total: int
    query: str
    record_count: int


ProgressCallback = Callable[[ScrapeProgress], None]


def scrape_searches(
    queries: Iterable[str],
    *,
    script: str,
    out_dir: Path,
    audio: str,
    clip_types: str,
    delay: float,
    retries: int,
    limit: int | None = None,
    workers: int = 1,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_queries = list(queries)
    if workers < 1:
        raise ValueError("workers must be at least 1.")

    indexed_records = fetch_all_searches(
        normalized_queries,
        script=script,
        retries=retries,
        limit=limit,
        delay=delay,
        workers=workers,
        progress_callback=progress_callback,
    )
    records = [
        record
        for _, parsed_records in sorted(indexed_records, key=lambda item: item[0])
        for record in parsed_records
    ]

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if audio == "clips":
            add_audio_clips(client, records, out_dir=out_dir, clip_types=clip_types, retries=retries)

    write_results(out_dir, records)
    write_manifest(out_dir, queries=normalized_queries, script=script, records=records, audio=audio)
    return records


def fetch_all_searches(
    queries: list[str],
    *,
    script: str,
    retries: int,
    limit: int | None,
    delay: float,
    workers: int,
    progress_callback: ProgressCallback | None,
) -> list[tuple[int, list[dict[str, Any]]]]:
    if not queries:
        return []

    if workers == 1 or len(queries) == 1:
        return fetch_all_searches_sequential(
            queries,
            script=script,
            retries=retries,
            limit=limit,
            delay=delay,
            progress_callback=progress_callback,
        )

    indexed_records: list[tuple[int, list[dict[str, Any]]]] = []
    completed = 0
    max_workers = min(workers, len(queries))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_and_parse_search,
                query,
                script=script,
                retries=retries,
                limit=limit,
            ): (position, query)
            for position, query in enumerate(queries)
        }

        for future in as_completed(futures):
            position, query = futures[future]
            parsed = future.result()
            indexed_records.append((position, parsed))
            completed += 1
            emit_progress(
                progress_callback,
                completed=completed,
                total=len(queries),
                query=query,
                record_count=len(parsed),
            )

    return indexed_records


def fetch_all_searches_sequential(
    queries: list[str],
    *,
    script: str,
    retries: int,
    limit: int | None,
    delay: float,
    progress_callback: ProgressCallback | None,
) -> list[tuple[int, list[dict[str, Any]]]]:
    indexed_records: list[tuple[int, list[dict[str, Any]]]] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for index, query in enumerate(queries):
            parsed = fetch_and_parse_search_with_client(
                client,
                query,
                script=script,
                retries=retries,
                limit=limit,
            )
            indexed_records.append((index, parsed))
            emit_progress(
                progress_callback,
                completed=index + 1,
                total=len(queries),
                query=query,
                record_count=len(parsed),
            )

            if delay > 0 and index < len(queries) - 1:
                time.sleep(delay)

    return indexed_records


def fetch_and_parse_search(
    query: str,
    *,
    script: str,
    retries: int,
    limit: int | None,
) -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        return fetch_and_parse_search_with_client(
            client,
            query,
            script=script,
            retries=retries,
            limit=limit,
        )


def fetch_and_parse_search_with_client(
    client: httpx.Client,
    query: str,
    *,
    script: str,
    retries: int,
    limit: int | None,
) -> list[dict[str, Any]]:
    html = fetch_search_html(client, query=query, script=script, retries=retries)
    parsed = parse_search_results(html, query=query, script=script)
    if limit is not None:
        return parsed[:limit]
    return parsed


def emit_progress(
    callback: ProgressCallback | None,
    *,
    completed: int,
    total: int,
    query: str,
    record_count: int,
) -> None:
    if callback is not None:
        callback(
            ScrapeProgress(
                completed=completed,
                total=total,
                query=query,
                record_count=record_count,
            )
        )


def fetch_search_html(
    client: httpx.Client,
    *,
    query: str,
    script: str,
    retries: int,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.get(SEARCH_URL, params={"search": query, "script": script})
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 8))

    assert last_error is not None
    raise last_error


def add_audio_clips(
    client: httpx.Client,
    records: list[dict[str, Any]],
    *,
    out_dir: Path,
    clip_types: str,
    retries: int,
) -> None:
    requested_regions = _requested_regions(clip_types)
    source_cache: dict[str, Path] = {}

    for record in records:
        audio = record.get("audio") or {}
        source_url = audio.get("source_url")
        regions = audio.get("regions") or {}
        if not source_url:
            continue

        source_path = source_cache.get(source_url)
        if source_path is None:
            source_path = out_dir / "audio" / "source" / f"{recording_id(source_url)}.mp3"
            download_audio(client, source_url, source_path, retries=retries)
            source_cache[source_url] = source_path

        audio["source_path"] = _relative_posix(source_path, out_dir)
        clips: dict[str, str] = {}
        for region_name in requested_regions:
            region = regions.get(region_name)
            if not region:
                continue
            clip_path = out_dir / "audio" / "clips" / f"{record['entry_id']}_{region_name}.mp3"
            trim_audio_clip(source_path, clip_path, start=region["start"], end=region["end"])
            clips[f"{region_name}_path"] = _relative_posix(clip_path, out_dir)
        audio["clips"] = clips


def download_audio(
    client: httpx.Client,
    source_url: str,
    destination: Path,
    *,
    retries: int,
) -> None:
    if destination.exists():
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.get(source_url)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 8))

    assert last_error is not None
    raise last_error


def write_results(out_dir: Path, records: list[dict[str, Any]]) -> None:
    results_path = out_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            output.write("\n")


def write_manifest(
    out_dir: Path,
    *,
    queries: list[str],
    script: str,
    records: list[dict[str, Any]],
    audio: str,
) -> None:
    manifest = {
        "source": "Derja.Ninja",
        "source_url": "https://derja.ninja/",
        "generated_at": datetime.now(UTC).isoformat(),
        "script": script,
        "queries": queries,
        "record_count": len(records),
        "audio_mode": audio,
        "text_license": "CC BY-SA 4.0",
        "text_attribution": "Derja.Ninja",
        "audio_rights": "All rights reserved by Derja.Ninja",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def recording_id(source_url: str) -> str:
    match = re.search(r"/([^/]+)\.mp3(?:$|\?)", source_url)
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", source_url).strip("_") or "recording"


def _requested_regions(clip_types: str) -> tuple[str, ...]:
    if clip_types == "term":
        return ("term",)
    if clip_types == "sentence":
        return ("sentence",)
    return ("term", "sentence")


def _relative_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()
