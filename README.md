# NINJA DERJA SCRAPER

Professional terminal scraper for Derja.Ninja search results, focused on Tunisian Arabic / `بالتونسي` queries.

It reads words or sentences, scrapes the top Derja.Ninja search samples, writes clean JSONL + manifest files, and can optionally download and trim timestamped audio clips when you have permission to use the recordings.

## Quick Start

Install locally:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Put your words in the fixed input file:

```text
input/input.txt
```

One query per line:

```text
برشا
سلام
شنوة
```

Run the batch scraper:

```powershell
ninja-derja scrape
```

The CLI uses `input/input.txt` by default, runs with parallel workers, and shows progress with remaining time in real terminals.

## Interactive CLI

Open the branded terminal app:

```powershell
ninja-derja
```

From there you can:

- scrape one word or sentence
- scrape from `input/input.txt` or another text file
- edit config values from the terminal
- review the latest output summary

Arabic input is handled with a custom right-to-left prompt so words like `سلام` are not typed backwards in the interactive mode.

## Common Commands

Scrape the default file:

```powershell
ninja-derja scrape
```

Scrape one query directly:

```powershell
ninja-derja scrape "برشا"
```

Scrape another UTF-8 file:

```powershell
ninja-derja scrape --file input/input.txt
```

Take only the top 3 samples per query with 8 workers:

```powershell
ninja-derja scrape --top-results 3 --workers 8
```

Write to a different output directory:

```powershell
ninja-derja scrape --out output/run-01
```

Create or show the config:

```powershell
ninja-derja config init
ninja-derja config show
```

Edit config from the command line:

```powershell
ninja-derja config edit --top-results 5 --workers 6 --no-download-audio
```

## Configuration

Default config path:

```text
ninja-derja.toml
```

Template:

```toml
output_dir = "output/derja"
input_path = "input/input.txt"
top_results = 10
script = "arabic"
download_audio = false
clip_types = "both"
delay = 0.0
retries = 3
workers = 4
audio_permission_acknowledged = false
```

Important settings:

- `input_path`: default word list used by `ninja-derja scrape`
- `top_results`: maximum search results saved per query
- `download_audio`: whether to download and trim clips by default
- `clip_types`: `both`, `term`, or `sentence`
- `delay`: delay between sequential requests; default is `0.0`
- `workers`: number of parallel search workers
- `audio_permission_acknowledged`: required for audio clips if you enable audio from config

## Audio Clips

Text entries are attributed to Derja.Ninja under the site's CC BY-SA notice. Audio recordings are guarded because Derja.Ninja marks recordings as all rights reserved.

To download source MP3 files and trim clips:

```powershell
ninja-derja scrape "برشا" --download-audio --clip-types both --i-have-audio-permission
```

The scraper downloads each source MP3 once, then trims term and sentence clips from embedded timestamps when available.

## Output

Default output:

```text
output/derja/results.jsonl
output/derja/manifest.json
output/derja/audio/source/
output/derja/audio/clips/
```

Each JSONL record includes:

- query and script
- result rank and entry URL
- Arabic term, transliteration, and English definition
- example sentence fields
- audio source URL and timestamp regions
- clip paths when audio clipping is enabled

## Testing

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run a live metadata smoke test:

```powershell
ninja-derja scrape "برشا" --top-results 1 --audio metadata --out output/smoke
```

## Fresh Project Cleanup

Generated data is ignored by git. To return to a fresh workspace, remove:

```text
output/
.pytest_cache/
derja_scraper.egg-info/
```

Keep `input/input.txt`, `ninja-derja.example.toml`, and source files.




# Option B : Si vous installez webrtcvad-wheels
pip install webrtcvad-wheels
python process_derja_audio.py -i results.jsonl -o output_clean --vad-mode webrtc

# Option C : Silero (meilleure qualité, mais télécharge un modèle ~20MB)
pip install torch torchaudio
python process_derja_audio.py -i results.jsonl -o output_clean --vad-mode silero

