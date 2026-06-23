from __future__ import annotations

import json
import re
from copy import copy
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


BASE_URL = "https://derja.ninja"


def parse_search_results(html: str, *, query: str, script: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results = soup.select("li.search-result")
    records: list[dict[str, Any]] = []

    for rank, result in enumerate(results, start=1):
        entry_href = _entry_href(result)
        entry_id = entry_href.rstrip("/").split("/")[-1] if entry_href else None
        term_block = result.select_one(".search-result__term_in_arabic")
        example_arabic_block = result.select_one(".search_result__example_sentence_in_arabic")

        records.append(
            {
                "query": query,
                "script": script,
                "rank": rank,
                "entry_id": entry_id,
                "entry_url": urljoin(BASE_URL, entry_href) if entry_href else None,
                "term_arabic": _clean_container_text(
                    term_block,
                    remove_selectors=(".js-play", ".transliterate-text"),
                ),
                "term_transliteration": _text(term_block.select_one(".transliterate-text"))
                if term_block
                else None,
                "definition_english": _definition_text(result),
                "example_sentence_english": _text(
                    result.select_one(".search_result__example_sentence_in_english .example-sentence")
                ),
                "example_sentence_arabic": _text(
                    example_arabic_block.select_one(".example-sentence")
                    if example_arabic_block
                    else None
                ),
                "example_sentence_transliteration": _text(
                    example_arabic_block.select_one(".transliterate-text")
                    if example_arabic_block
                    else None
                ),
                "audio": _audio_payload(result),
            }
        )

    return records


def _entry_href(result: Tag) -> str | None:
    link = result.select_one('a[href^="/e/"]')
    if not link:
        return None
    href = link.get("href")
    return str(href) if href else None


def _definition_text(result: Tag) -> str | None:
    definition = result.select_one(".search-result__definition_in_english")
    return _clean_container_text(definition, remove_selectors=("a",))


def _audio_payload(result: Tag) -> dict[str, Any]:
    source_url: str | None = None
    regions: dict[str, dict[str, float]] = {}

    for play in result.select(".js-play"):
        name = play.get("data-region-name")
        audio = play.select_one("audio")
        if audio and not source_url:
            source_url = str(audio.get("src") or "") or None

        script = play.select_one('script[type="application/json"]')
        if not name or not script:
            continue

        try:
            recording_info = json.loads(script.get_text(strip=True))
        except json.JSONDecodeError:
            continue

        region = recording_info.get(str(name))
        if not isinstance(region, dict):
            continue

        start = region.get("start")
        end = region.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            regions[str(name)] = {"start": float(start), "end": float(end)}

    return {"source_url": source_url, "regions": regions, "clips": {}}


def _clean_container_text(
    node: Tag | None,
    *,
    remove_selectors: tuple[str, ...],
) -> str | None:
    if node is None:
        return None

    cleaned = copy(node)
    for selector in remove_selectors:
        for child in cleaned.select(selector):
            child.decompose()
    return _normalize_spaces(cleaned.get_text(" ", strip=True))


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    return _normalize_spaces(node.get_text(" ", strip=True))


def _normalize_spaces(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None
