import json
from pathlib import Path

from derja_scraper.scraper import ScrapeProgress, scrape_searches


def test_scrape_searches_uses_workers_and_reports_progress(monkeypatch, tmp_path):
    html = (Path(__file__).parent / "fixtures" / "search_results_arabic.html").read_text(
        encoding="utf-8"
    )
    requested = []
    progress_events: list[ScrapeProgress] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, params=None):
            requested.append(params["search"])
            return FakeResponse(html)

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    monkeypatch.setattr("derja_scraper.scraper.httpx.Client", FakeClient)

    records = scrape_searches(
        ["برشا", "سلام"],
        script="arabic",
        out_dir=tmp_path,
        audio="metadata",
        clip_types="both",
        delay=0,
        retries=0,
        limit=1,
        workers=2,
        progress_callback=progress_events.append,
    )

    assert sorted(requested) == ["برشا", "سلام"]
    assert [record["query"] for record in records] == ["برشا", "سلام"]
    assert [event.total for event in progress_events] == [2, 2]
    assert sorted(event.completed for event in progress_events) == [1, 2]

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["queries"] == ["برشا", "سلام"]
