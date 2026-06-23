from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg


def trim_audio_clip(source: Path, destination: Path, *, start: float, end: float) -> None:
    if end <= start:
        raise ValueError("Audio clip end must be greater than start.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.6f}",
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(destination),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
