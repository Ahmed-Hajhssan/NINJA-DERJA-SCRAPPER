from __future__ import annotations

from enum import Enum
from pathlib import Path
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from derja_scraper.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_PATH,
    ScraperConfig,
    load_config,
    save_config,
)
from derja_scraper.display import terminal_text
from derja_scraper.display import rtl_input_line
from derja_scraper.scraper import ScrapeProgress
from derja_scraper.scraper import scrape_searches


class AudioMode(str, Enum):
    metadata = "metadata"
    clips = "clips"


class ClipTypes(str, Enum):
    both = "both"
    term = "term"
    sentence = "sentence"


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_output_encoding()


app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="NINJA DERJA SCRAPER terminal app.",
)
config_app = typer.Typer(help="Manage scraper configuration.")
console = Console(width=120)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Scrape Derja.Ninja search results."""
    if ctx.invoked_subcommand is None:
        run_interactive(DEFAULT_CONFIG_PATH)


@app.command()
def scrape(
    terms: Optional[list[str]] = typer.Argument(None, help="Search terms to scrape."),
    queries: Optional[Path] = typer.Option(
        None,
        "--queries",
        "--file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="UTF-8 text file with one search query per line.",
    ),
    input_path: Optional[Path] = typer.Option(
        None,
        "--input",
        help="Default batch input file used when no query args or --file are provided.",
    ),
    config: Path = typer.Option(
        DEFAULT_CONFIG_PATH,
        "--config",
        help="Path to a NINJA DERJA SCRAPER TOML config file.",
    ),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory."),
    script: Optional[str] = typer.Option(None, "--script", help="Derja.Ninja search script."),
    audio: Optional[AudioMode] = typer.Option(None, "--audio", help="Audio handling mode."),
    download_audio: bool = typer.Option(
        False,
        "--download-audio",
        help="Shortcut for --audio clips.",
    ),
    clip_types: Optional[ClipTypes] = typer.Option(
        None,
        "--clip-types",
        help="Which timestamped audio regions to clip.",
    ),
    i_have_audio_permission: bool = typer.Option(
        False,
        "--i-have-audio-permission",
        help="Required before downloading/trimming Derja.Ninja audio.",
    ),
    delay: Optional[float] = typer.Option(None, "--delay", min=0.0, help="Delay between searches."),
    retries: Optional[int] = typer.Option(None, "--retries", min=0, help="HTTP retries per request."),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        min=1,
        help="Number of parallel search workers.",
    ),
    top_results: Optional[int] = typer.Option(
        None,
        "--top-results",
        "--limit",
        min=1,
        help="Maximum results to keep per query.",
    ),
) -> None:
    run_scrape(
        terms=terms or [],
        queries=queries,
        input_path=input_path,
        config_path=config,
        out=out,
        script=script,
        audio=audio,
        download_audio=download_audio,
        clip_types=clip_types,
        i_have_audio_permission=i_have_audio_permission,
        delay=delay,
        retries=retries,
        workers=workers,
        top_results=top_results,
    )


@app.command(hidden=True)
def search(
    terms: Optional[list[str]] = typer.Argument(None, help="Search terms to scrape."),
    queries: Optional[Path] = typer.Option(
        None,
        "--queries",
        "--file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    input_path: Optional[Path] = typer.Option(None, "--input"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config"),
    out: Optional[Path] = typer.Option(None, "--out"),
    script: Optional[str] = typer.Option(None, "--script"),
    audio: Optional[AudioMode] = typer.Option(None, "--audio"),
    download_audio: bool = typer.Option(False, "--download-audio"),
    clip_types: Optional[ClipTypes] = typer.Option(None, "--clip-types"),
    i_have_audio_permission: bool = typer.Option(False, "--i-have-audio-permission"),
    delay: Optional[float] = typer.Option(None, "--delay", min=0.0),
    retries: Optional[int] = typer.Option(None, "--retries", min=0),
    workers: Optional[int] = typer.Option(None, "--workers", min=1),
    top_results: Optional[int] = typer.Option(None, "--top-results", "--limit", min=1),
) -> None:
    run_scrape(
        terms=terms or [],
        queries=queries,
        input_path=input_path,
        config_path=config,
        out=out,
        script=script,
        audio=audio,
        download_audio=download_audio,
        clip_types=clip_types,
        i_have_audio_permission=i_have_audio_permission,
        delay=delay,
        retries=retries,
        workers=workers,
        top_results=top_results,
    )


@config_app.command("init")
def config_init(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file to create."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config."),
) -> None:
    if config.exists() and not force:
        console.print(f"[yellow]Config already exists:[/yellow] {config}")
        raise typer.Exit(1)

    save_config(config, DEFAULT_CONFIG)
    console.print(f"[green]Created config:[/green] {config}")


@config_app.command("show")
def config_show(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file to read."),
) -> None:
    show_config(load_config(config), config)


@config_app.command("edit")
def config_edit(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file to update."),
    top_results: Optional[int] = typer.Option(None, "--top-results", min=1),
    output_dir: Optional[Path] = typer.Option(None, "--out"),
    input_path: Optional[Path] = typer.Option(None, "--input"),
    script: Optional[str] = typer.Option(None, "--script"),
    download_audio: bool = typer.Option(False, "--download-audio"),
    no_download_audio: bool = typer.Option(False, "--no-download-audio"),
    clip_types: Optional[ClipTypes] = typer.Option(None, "--clip-types"),
    delay: Optional[float] = typer.Option(None, "--delay", min=0.0),
    retries: Optional[int] = typer.Option(None, "--retries", min=0),
    workers: Optional[int] = typer.Option(None, "--workers", min=1),
    ack_audio_permission: bool = typer.Option(False, "--ack-audio-permission"),
) -> None:
    if download_audio and no_download_audio:
        console.print("[red]Choose only one of --download-audio or --no-download-audio.[/red]")
        raise typer.Exit(2)

    current = load_config(config)
    updates = {
        "top_results": top_results,
        "output_dir": output_dir,
        "input_path": input_path,
        "script": script,
        "clip_types": clip_types.value if clip_types else None,
        "delay": delay,
        "retries": retries,
        "workers": workers,
    }
    if download_audio:
        updates["download_audio"] = True
    if no_download_audio:
        updates["download_audio"] = False
    if ack_audio_permission:
        updates["audio_permission_acknowledged"] = True

    next_config = current.with_updates(
        **{key: value for key, value in updates.items() if value is not None}
    )
    save_config(config, next_config)
    console.print(f"[green]Updated config:[/green] {config}")
    show_config(next_config, config)


app.add_typer(config_app, name="config")


def run_scrape(
    *,
    terms: list[str],
    queries: Path | None,
    input_path: Path | None,
    config_path: Path,
    out: Path | None,
    script: str | None,
    audio: AudioMode | None,
    download_audio: bool,
    clip_types: ClipTypes | None,
    i_have_audio_permission: bool,
    delay: float | None,
    retries: int | None,
    workers: int | None,
    top_results: int | None,
) -> list[dict]:
    config = load_config(config_path)
    effective_input = input_path or config.input_path
    query_values = collect_queries(terms, queries, effective_input)
    if not query_values:
        console.print(
            "[red]Provide a query, pass --queries/--file, or put one query per line in "
            f"{effective_input}.[/red]"
        )
        raise typer.Exit(2)

    audio_mode = effective_audio_mode(config, audio, download_audio)
    audio_permission = (
        i_have_audio_permission or config.audio_permission_acknowledged
    )
    if audio_mode == "clips" and not audio_permission:
        console.print(
            "[red]Audio recordings are marked all rights reserved by Derja.Ninja. "
            "Use --i-have-audio-permission or set audio_permission_acknowledged = true "
            "in the config before downloading or trimming audio.[/red]"
        )
        raise typer.Exit(2)

    output_dir = out or config.output_dir
    with make_progress(len(query_values)) as progress:
        task_id = progress.add_task("Scraping", total=len(query_values))

        def on_progress(event: ScrapeProgress) -> None:
            progress.update(
                task_id,
                completed=event.completed,
                description=f"Scraping {event.completed}/{event.total}: {terminal_text(event.query)}",
            )

        records = scrape_searches(
            query_values,
            script=script or config.script,
            out_dir=output_dir,
            audio=audio_mode,
            clip_types=(clip_types.value if clip_types else config.clip_types),
            delay=config.delay if delay is None else delay,
            retries=config.retries if retries is None else retries,
            limit=config.top_results if top_results is None else top_results,
            workers=config.workers if workers is None else workers,
            progress_callback=on_progress,
        )
    print_scrape_summary(records, output_dir)
    return records


def make_progress(total: int) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TextColumn("elapsed"),
        TimeElapsedColumn(),
        console=console,
        disable=not console.is_terminal or total < 2,
    )


def effective_audio_mode(
    config: ScraperConfig,
    audio: AudioMode | None,
    download_audio: bool,
) -> str:
    if download_audio:
        return "clips"
    if audio is not None:
        return audio.value
    return "clips" if config.download_audio else "metadata"


def run_interactive(config_path: Path) -> None:
    config = load_config(config_path)
    print_banner(config_path, config)

    while True:
        console.print()
        console.print("[bold]Choose an action[/bold]")
        console.print("1. Scrape one word or sentence")
        console.print("2. Scrape from a txt file")
        console.print("3. Edit config")
        console.print("4. Show last output summary")
        console.print("5. Exit")
        choice = Prompt.ask("Action", choices=["1", "2", "3", "4", "5"], default="1")

        if choice == "1":
            query = ask_rtl("Word or sentence").strip()
            if query:
                run_scrape_from_interactive([query], None, config_path)
        elif choice == "2":
            file_path = Path(Prompt.ask("Path to txt file", default=str(config.input_path)).strip())
            run_scrape_from_interactive([], file_path, config_path)
        elif choice == "3":
            config = edit_config_interactively(config_path, config)
        elif choice == "4":
            show_last_summary(config.output_dir)
        else:
            console.print("[bold]Goodbye.[/bold]")
            return


def run_scrape_from_interactive(
    terms: list[str],
    queries: Path | None,
    config_path: Path,
) -> None:
    run_scrape(
        terms=terms,
        queries=queries,
        input_path=None,
        config_path=config_path,
        out=None,
        script=None,
        audio=None,
        download_audio=False,
        clip_types=None,
        i_have_audio_permission=False,
        delay=None,
        retries=None,
        workers=None,
        top_results=None,
    )


def ask_rtl(prompt: str) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return Prompt.ask(prompt)

    try:
        return _read_rtl_line(prompt)
    except (EOFError, OSError):
        return Prompt.ask(prompt)


def _read_rtl_line(prompt: str) -> str:
    buffer: list[str] = []
    last_line = ""

    def redraw() -> None:
        nonlocal last_line
        line = rtl_input_line(prompt, "".join(buffer))
        padding = " " * max(0, len(last_line) - len(line))
        sys.stdout.write("\r" + line + padding + "\r" + line)
        sys.stdout.flush()
        last_line = line

    redraw()
    reader = _KeyReader()
    try:
        while True:
            char = reader.read()
            if char in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if char == "\x03":
                raise KeyboardInterrupt
            if char in ("\b", "\x7f"):
                if buffer:
                    buffer.pop()
                    redraw()
                continue
            if char and char.isprintable():
                buffer.append(char)
                redraw()
    finally:
        reader.close()


class _KeyReader:
    def __init__(self) -> None:
        self._old_settings = None
        if sys.platform == "win32":
            import msvcrt

            self._msvcrt = msvcrt
        else:
            import termios
            import tty

            self._termios = termios
            self._fd = sys.stdin.fileno()
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setraw(self._fd)

    def read(self) -> str:
        if sys.platform == "win32":
            char = self._msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                self._msvcrt.getwch()
                return ""
            return char
        return sys.stdin.read(1)

    def close(self) -> None:
        if self._old_settings is not None:
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old_settings)


def edit_config_interactively(config_path: Path, config: ScraperConfig) -> ScraperConfig:
    console.print(Panel("Edit defaults used by interactive scraping.", title="Config"))
    next_config = config.with_updates(
        top_results=IntPrompt.ask("Top results", default=config.top_results),
        output_dir=Path(Prompt.ask("Output directory", default=str(config.output_dir))),
        input_path=Path(Prompt.ask("Input txt file", default=str(config.input_path))),
        script=Prompt.ask("Script", default=config.script),
        download_audio=Confirm.ask("Download and trim audio clips?", default=config.download_audio),
        clip_types=Prompt.ask(
            "Clip types",
            choices=["both", "term", "sentence"],
            default=config.clip_types,
        ),
        delay=FloatPrompt.ask("Delay between searches", default=config.delay),
        retries=IntPrompt.ask("HTTP retries", default=config.retries),
        workers=IntPrompt.ask("Parallel workers", default=config.workers),
    )

    if next_config.download_audio:
        next_config = next_config.with_updates(
            audio_permission_acknowledged=Confirm.ask(
                "Do you have permission to download/trim Derja.Ninja audio?",
                default=config.audio_permission_acknowledged,
            )
        )

    save_config(config_path, next_config)
    console.print(f"[green]Saved config:[/green] {config_path}")
    show_config(next_config, config_path)
    return next_config


def print_banner(config_path: Path, config: ScraperConfig) -> None:
    banner = Text()
    banner.append("NINJA DERJA SCRAPER\n", style="bold cyan")
    banner.append("Tunisian Arabic search data, cleanly scraped.", style="white")
    console.print(Panel(banner, subtitle=f"config: {config_path}", border_style="cyan"))
    show_config(config, config_path)


def show_config(config: ScraperConfig, config_path: Path) -> None:
    table = Table(title=f"Config: {config_path}")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("output_dir", config.output_dir.as_posix())
    table.add_row("input_path", config.input_path.as_posix())
    table.add_row("top_results", str(config.top_results))
    table.add_row("script", config.script)
    table.add_row("download_audio", str(config.download_audio).lower())
    table.add_row("clip_types", config.clip_types)
    table.add_row("delay", str(config.delay))
    table.add_row("retries", str(config.retries))
    table.add_row("workers", str(config.workers))
    table.add_row(
        "audio_permission_acknowledged",
        str(config.audio_permission_acknowledged).lower(),
    )
    console.print(table)


def print_scrape_summary(records: list[dict], out: Path) -> None:
    table = Table(title="Scrape Summary")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Query", style="white")
    table.add_column("Term", style="white")
    table.add_column("Definition", style="green")

    for index, record in enumerate(records[:10], start=1):
        table.add_row(
            str(index),
            terminal_text(record.get("query") or ""),
            terminal_text(record.get("term_arabic") or ""),
            str(record.get("definition_english") or ""),
        )

    console.print(table)
    console.print(f"[green]Wrote {len(records)} records to {out / 'results.jsonl'}[/green]")


def show_last_summary(out: Path) -> None:
    results_path = out / "results.jsonl"
    if not results_path.exists():
        console.print(f"[yellow]No results found at {results_path}[/yellow]")
        return

    import json

    records = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print_scrape_summary(records, out)


def collect_queries(
    terms: list[str],
    queries_file: Path | None,
    default_queries_file: Path | None = None,
) -> list[str]:
    values: list[str] = [_normalize_query(term) for term in terms if _normalize_query(term)]
    selected_file = queries_file
    if selected_file is None and not values and default_queries_file is not None:
        selected_file = default_queries_file

    if selected_file and selected_file.exists():
        values.extend(_read_queries_file(selected_file))
    return values


def _read_queries_file(path: Path) -> list[str]:
    queries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        query = _normalize_query(line)
        if query and not query.startswith("#"):
            queries.append(query)
    return queries


def _normalize_query(value: str) -> str:
    return value.strip().removeprefix("\ufeff").strip()
