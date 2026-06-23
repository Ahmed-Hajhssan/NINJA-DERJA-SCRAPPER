from pathlib import Path

from derja_scraper.config import DEFAULT_CONFIG, load_config, save_config


def test_load_config_returns_defaults_when_file_is_missing(tmp_path):
    config = load_config(tmp_path / "missing.toml")

    assert config.top_results == DEFAULT_CONFIG.top_results
    assert config.output_dir == DEFAULT_CONFIG.output_dir
    assert config.input_path == Path("input/input.txt")
    assert config.delay == 0.0
    assert config.workers == 4
    assert config.download_audio is False


def test_load_config_merges_toml_values_with_defaults(tmp_path):
    config_path = tmp_path / "ninja-derja.toml"
    config_path.write_text(
        "\n".join(
            [
                'output_dir = "output/custom"',
                "top_results = 3",
                'input_path = "input/custom.txt"',
                "download_audio = true",
                'clip_types = "term"',
                "delay = 0.25",
                "workers = 2",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.output_dir == Path("output/custom")
    assert config.input_path == Path("input/custom.txt")
    assert config.top_results == 3
    assert config.download_audio is True
    assert config.clip_types == "term"
    assert config.delay == 0.25
    assert config.workers == 2
    assert config.script == DEFAULT_CONFIG.script


def test_save_config_writes_readable_toml(tmp_path):
    config_path = tmp_path / "ninja-derja.toml"
    config = DEFAULT_CONFIG.with_updates(top_results=7, download_audio=True)

    save_config(config_path, config)

    reloaded = load_config(config_path)
    assert reloaded.top_results == 7
    assert reloaded.download_audio is True
