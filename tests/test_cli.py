import json
from pathlib import Path

from typer.testing import CliRunner

from derja_scraper.cli import app, collect_queries


runner = CliRunner()


def test_audio_clips_require_explicit_permission(tmp_path):
    result = runner.invoke(
        app,
        [
            "search",
            "برشا",
            "--config",
            str(tmp_path / "missing.toml"),
            "--out",
            str(tmp_path),
            "--audio",
            "clips",
        ],
    )

    assert result.exit_code == 2
    assert "--i-have-audio-permission" in result.output


def test_scrape_accepts_query_args_and_query_file(monkeypatch, tmp_path):
    queries_file = tmp_path / "queries.txt"
    queries_file.write_text("عسلامة\n\n", encoding="utf-8")

    html = (Path(__file__).parent / "fixtures" / "search_results_arabic.html").read_text(
        encoding="utf-8"
    )
    requested = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, params=None):
            requested.append((url, params))
            return FakeResponse(html)

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    monkeypatch.setattr("derja_scraper.scraper.httpx.Client", FakeClient)

    result = runner.invoke(
        app,
        [
            "scrape",
            "برشا",
            "--queries",
            str(queries_file),
            "--config",
            str(tmp_path / "missing.toml"),
            "--out",
            str(tmp_path / "out"),
            "--delay",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert requested == [
        ("https://derja.ninja/search", {"search": "برشا", "script": "arabic"}),
        ("https://derja.ninja/search", {"search": "عسلامة", "script": "arabic"}),
    ]

    lines = (tmp_path / "out" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first_record = json.loads(lines[0])
    assert first_record["query"] == "برشا"
    assert first_record["audio"]["source_url"].endswith("/2121.mp3")

    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "Derja.Ninja"
    assert manifest["text_license"] == "CC BY-SA 4.0"
    assert manifest["audio_rights"] == "All rights reserved by Derja.Ninja"
    assert manifest["queries"] == ["برشا", "عسلامة"]
    assert manifest["record_count"] == 2


def test_scrape_uses_config_file_defaults(monkeypatch, tmp_path):
    config_path = tmp_path / "ninja-derja.toml"
    config_path.write_text(
        "\n".join(
            [
                f'output_dir = "{(tmp_path / "configured-out").as_posix()}"',
                "top_results = 1",
                "delay = 0",
                "retries = 0",
                "download_audio = false",
            ]
        ),
        encoding="utf-8",
    )

    html = (Path(__file__).parent / "fixtures" / "search_results_arabic.html").read_text(
        encoding="utf-8"
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, params=None):
            return FakeResponse(html)

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    monkeypatch.setattr("derja_scraper.scraper.httpx.Client", FakeClient)

    result = runner.invoke(
        app,
        [
            "scrape",
            "برشا",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0, result.output
    lines = (tmp_path / "configured-out" / "results.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1


def test_scrape_uses_configured_input_file_when_no_query_args(monkeypatch, tmp_path):
    input_path = tmp_path / "input" / "input.txt"
    input_path.parent.mkdir()
    input_path.write_text("# one query per line\n\nبرشا\nسلام\n", encoding="utf-8")

    config_path = tmp_path / "ninja-derja.toml"
    config_path.write_text(
        "\n".join(
            [
                f'output_dir = "{(tmp_path / "configured-out").as_posix()}"',
                f'input_path = "{input_path.as_posix()}"',
                "top_results = 1",
                "delay = 0",
                "workers = 2",
                "retries = 0",
            ]
        ),
        encoding="utf-8",
    )

    html = (Path(__file__).parent / "fixtures" / "search_results_arabic.html").read_text(
        encoding="utf-8"
    )
    requested = []

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

    result = runner.invoke(app, ["scrape", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert sorted(requested) == ["برشا", "سلام"]

    manifest = json.loads(
        (tmp_path / "configured-out" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["queries"] == ["برشا", "سلام"]


def test_config_init_and_show(tmp_path):
    config_path = tmp_path / "ninja-derja.toml"

    init_result = runner.invoke(
        app,
        ["config", "init", "--config", str(config_path)],
    )
    assert init_result.exit_code == 0, init_result.output
    assert config_path.exists()

    show_result = runner.invoke(
        app,
        ["config", "show", "--config", str(config_path)],
    )
    assert show_result.exit_code == 0, show_result.output
    assert "top_results" in show_result.output
    assert "output/derja" in show_result.output
    assert "input/input.txt" in show_result.output


def test_collect_queries_uses_default_input_file_and_skips_comments(tmp_path):
    default_input = tmp_path / "input" / "input.txt"
    default_input.parent.mkdir()
    default_input.write_text("\ufeff# words\nبرشا\n\n# sentences\nسلام\n", encoding="utf-8")

    assert collect_queries([], None, default_input) == ["برشا", "سلام"]


def test_root_command_opens_branded_interactive_shell():
    result = runner.invoke(app, input="5\n")

    assert result.exit_code == 0, result.output
    assert "NINJA DERJA SCRAPER" in result.output
    assert "Scrape one word" in result.output


def test_collect_queries_strips_utf8_bom_from_file(tmp_path):
    queries_file = tmp_path / "words.txt"
    queries_file.write_text("\ufeffبرشا\nعسلامة\n", encoding="utf-8")

    assert collect_queries([], queries_file) == ["برشا", "عسلامة"]
