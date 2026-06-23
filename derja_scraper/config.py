from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_CONFIG_PATH = Path("ninja-derja.toml")
DEFAULT_INPUT_PATH = Path("input/input.txt")


@dataclass(frozen=True)
class ScraperConfig:
    output_dir: Path = Path("output/derja")
    input_path: Path = DEFAULT_INPUT_PATH
    top_results: int = 10
    script: str = "arabic"
    download_audio: bool = False
    clip_types: str = "both"
    delay: float = 0.0
    retries: int = 3
    workers: int = 4
    audio_permission_acknowledged: bool = False

    def with_updates(self, **updates: Any) -> "ScraperConfig":
        return replace(self, **updates)


DEFAULT_CONFIG = ScraperConfig()
VALID_CLIP_TYPES = {"both", "term", "sentence"}


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ScraperConfig:
    if not path.exists():
        return DEFAULT_CONFIG

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    updates: dict[str, Any] = {}

    for field_name in asdict(DEFAULT_CONFIG):
        if field_name in data:
            updates[field_name] = data[field_name]

    for path_field in ("output_dir", "input_path"):
        if path_field in updates:
            updates[path_field] = Path(updates[path_field])

    config = DEFAULT_CONFIG.with_updates(**updates)
    validate_config(config)
    return config


def save_config(path: Path, config: ScraperConfig) -> None:
    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(config), encoding="utf-8")


def validate_config(config: ScraperConfig) -> None:
    if config.top_results < 1:
        raise ValueError("top_results must be at least 1.")
    if config.delay < 0:
        raise ValueError("delay must be zero or greater.")
    if config.retries < 0:
        raise ValueError("retries must be zero or greater.")
    if config.workers < 1:
        raise ValueError("workers must be at least 1.")
    if config.clip_types not in VALID_CLIP_TYPES:
        raise ValueError("clip_types must be one of: both, term, sentence.")
    if not config.script.strip():
        raise ValueError("script cannot be empty.")


def to_toml(config: ScraperConfig) -> str:
    return "\n".join(
        [
            "# NINJA DERJA SCRAPER configuration",
            f'output_dir = "{config.output_dir.as_posix()}"',
            f'input_path = "{config.input_path.as_posix()}"',
            f"top_results = {config.top_results}",
            f'script = "{config.script}"',
            f"download_audio = {_toml_bool(config.download_audio)}",
            f'clip_types = "{config.clip_types}"',
            f"delay = {config.delay}",
            f"retries = {config.retries}",
            f"workers = {config.workers}",
            f"audio_permission_acknowledged = {_toml_bool(config.audio_permission_acknowledged)}",
            "",
        ]
    )


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
