import subprocess
from pathlib import Path

import imageio_ffmpeg

from derja_scraper.audio import trim_audio_clip
from derja_scraper.scraper import add_audio_clips


def test_trim_audio_clip_uses_bundled_ffmpeg(tmp_path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    source = tmp_path / "source.mp3"
    clip = tmp_path / "clip.mp3"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.5",
            str(source),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    trim_audio_clip(source, clip, start=0.25, end=0.75)

    assert clip.exists()
    assert clip.stat().st_size > 0


def test_add_audio_clips_downloads_source_once_and_records_paths(monkeypatch, tmp_path):
    downloads = []
    trimmed = []

    class FakeClient:
        def get(self, url):
            downloads.append(url)
            return FakeResponse(b"mp3 bytes")

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    def fake_trim(source, destination, *, start, end):
        trimmed.append((source, destination, start, end))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"clip")

    monkeypatch.setattr("derja_scraper.scraper.trim_audio_clip", fake_trim)

    records = [
        {
            "entry_id": "entry-1",
            "audio": {
                "source_url": "https://static.derjaninja.com/recordings/2121.mp3",
                "regions": {
                    "term": {"start": 1.0, "end": 2.0},
                    "sentence": {"start": 3.0, "end": 4.0},
                },
                "clips": {},
            },
        },
        {
            "entry_id": "entry-2",
            "audio": {
                "source_url": "https://static.derjaninja.com/recordings/2121.mp3",
                "regions": {"term": {"start": 5.0, "end": 6.0}},
                "clips": {},
            },
        },
    ]

    add_audio_clips(FakeClient(), records, out_dir=tmp_path, clip_types="both", retries=0)

    assert downloads == ["https://static.derjaninja.com/recordings/2121.mp3"]
    assert (tmp_path / "audio" / "source" / "2121.mp3").read_bytes() == b"mp3 bytes"
    assert records[0]["audio"]["source_path"] == "audio/source/2121.mp3"
    assert records[0]["audio"]["clips"] == {
        "term_path": "audio/clips/entry-1_term.mp3",
        "sentence_path": "audio/clips/entry-1_sentence.mp3",
    }
    assert records[1]["audio"]["source_path"] == "audio/source/2121.mp3"
    assert records[1]["audio"]["clips"] == {
        "term_path": "audio/clips/entry-2_term.mp3",
    }
    assert len(trimmed) == 3
