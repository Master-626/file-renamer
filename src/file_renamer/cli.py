"""Command Line Interface for file-renamer."""

from pathlib import Path
from typing import Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from file_renamer import __version__, history as history_module
from file_renamer.core import (
    build_rename_plan,
    execute_rename,
    execute_undo,
    find_files,
    preflight_rename,
)
from file_renamer.history import HistoryManager

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="file-renamer")
def cli():
    """File Renamer: Batch rename files with safety, previews, and undo history."""
    pass


@cli.command("patterns")
def patterns():
    """List all available rename transformation patterns."""
    table = Table(title="Available Patterns", header_style="bold magenta")
    table.add_column("Pattern", style="cyan")
    table.add_column("Description")
    table.add_column("Example (Before -> After)", style="green")

    table.add_row("lower", "Lowercase all characters", "File NAME.txt -> file name.txt")
    table.add_row("upper", "Uppercase the stem; keep the extension", "file name.txt -> FILE NAME.txt")
    table.add_row("title", "Capitalize each word", "my vacation.png -> My Vacation.png")
    table.add_row("kebab-spaces", "Convert whitespace to dashes", "my file test.doc -> my-file-test.doc")
    table.add_row("snake-spaces", "Convert whitespace to underscores", "my file test.doc -> my_file_test.doc")
    table.add_row("remove-numbers", "Strip all numeric digits", "img_001_final.jpg -> img__final.jpg")
    table.add_row(
        "remove-special",
        "Remove characters other than letters, numbers, underscores, and dashes",
        "doc#1 (v2).pdf -> doc1v2.pdf",
    )

    console.print(table)


def _preview_label(path: Path, root: Path) -> str:
    """Show a path relative to the rename root when it is not a bare filename."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


@cli.command("list")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("-e", "--ext", type=str, help="Filter by extension (e.g. .jpg, jpg, or .tar.gz)")
@click.option("-r", "--recursive", is_flag=True, help="Scan directory recursively")
def list_files(directory: Path, ext: Optional[str], recursive: bool):
    """List files in a directory that match filter criteria."""
    try:
        files = find_files(directory, recursive=recursive, extension=ext)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()

    if not files:
        console.print("[yellow]No files matched criteria.[/yellow]")
        return

    table = Table(title=f"Matched Files ({len(files)})", header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Relative Path", style="white")
    table.add_column("Size", justify="right", style="green")

    for idx, f in enumerate(files, 1):
        rel_path = f.relative_to(directory) if f != directory else f.name
        size = f"{f.stat().st_size:,} B"
        table.add_row(str(idx), str(rel_path), size)

    console.print(table)


@cli.command("rename")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option(
    "-p",
    "--pattern",
    type=click.Choice(
        ["lower", "upper", "title", "kebab-spaces", "snake-spaces", "remove-numbers", "remove-special"],
        case_sensitive=False,
    ),
    help="Pattern transformation to apply.",
)
@click.option("--prefix", default="", help="Prefix to prepend to filenames.")
@click.option("--suffix", default="", help="Suffix to append to filenames (before extension).")
@click.option(
    "--replace",
    "replacements",
    nargs=2,
    multiple=True,
    metavar="OLD NEW",
    help=(
        "Replace literal OLD with NEW in the original filename before other "
        "transforms. Repeatable. NEW may be empty to delete OLD."
    ),
)
@click.option("--sequence", is_flag=True, help="Add sequential numbering.")
@click.option("--start", default=1, type=int, help="Sequential number starting index.")
@click.option("--padding", default=2, type=int, help="Zero-padding width for sequence.")
@click.option("-e", "--ext", type=str, help="Target one extension, including a compound suffix such as .tar.gz.")
@click.option("-r", "--recursive", is_flag=True, help="Process subdirectories recursively.")
@click.option("-d", "--dry-run", is_flag=True, help="Simulate changes without modifying filesystem.")
def rename(
    directory: Path,
    pattern: Optional[str],
    prefix: str,
    suffix: str,
    replacements: Tuple[Tuple[str, str], ...],
    sequence: bool,
    start: int,
    padding: int,
    ext: Optional[str],
    recursive: bool,
    dry_run: bool,
):
    """Apply renaming patterns to files in the target directory."""
    try:
        files = find_files(directory, recursive=recursive, extension=ext)
        if not files:
            console.print("[yellow]No matching files found to rename.[/yellow]")
            return

        plan = build_rename_plan(
            files=files,
            pattern=pattern,
            prefix=prefix,
            suffix=suffix,
            sequence=sequence,
            start=start,
            padding=padding,
            replacements=replacements,
        )
    except Exception as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        raise click.Abort()

    changes = [item for item in plan if item.has_changed]

    if not changes:
        console.print("[green]No files require modification with current settings.[/green]")
        return

    table = Table(
        title=f"Proposed Plan: {len(changes)} files to rename" + (" (DRY RUN)" if dry_run else ""),
        header_style="bold blue",
    )
    table.add_column("Original Filename", style="dim")
    table.add_column("New Filename", style="bold green")

    for item in changes:
        table.add_row(_preview_label(item.src, directory), _preview_label(item.dst, directory))

    console.print(table)

    if dry_run:
        try:
            # Look up HISTORY_FILE at call time so tests can redirect it.
            preflight_rename(plan, history_module.HISTORY_FILE)
        except Exception as e:
            console.print(f"[bold red]Dry-run failed:[/bold red] {e}")
            console.print("[bold yellow]No changes were written to disk.[/bold yellow]")
            raise click.Abort()
        console.print("\n[bold yellow]Dry-run mode active.[/bold yellow] No changes were written to disk.")
        return

    try:
        renamed_count, tx_id = execute_rename(plan)
        console.print(
            Panel(
                f"[bold green]Successfully renamed {renamed_count} files.[/bold green]\n"
                f"Transaction ID: [cyan]{tx_id}[/cyan]\n"
                f"Use [bold cyan]file-renamer undo[/bold cyan] to revert this operation.",
                title="Operation Complete",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Execution failed:[/bold red] {e}")
        raise click.Abort()


@cli.command("history")
def history():
    """Show previous rename transactions."""
    history_mgr = HistoryManager()
    transactions = history_mgr.list_all()

    if not transactions:
        console.print("[yellow]No rename history found.[/yellow]")
        return

    table = Table(title="Rename Transaction History", header_style="bold blue")
    table.add_column("Transaction ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Files Affected", justify="right")
    table.add_column("Status", justify="center")

    for tx in transactions:
        status = "[red]Reverted[/red]" if tx.undone else "[green]Active[/green]"
        table.add_row(tx.id, tx.timestamp, str(len(tx.records)), status)

    console.print(table)


@cli.command("undo")
def undo():
    """Revert the most recent rename operation."""
    try:
        tx_id, reverted = execute_undo()
        table = Table(title=f"Undo Details (Tx: {tx_id})", header_style="bold yellow")
        table.add_column("Reverted From", style="dim")
        table.add_column("Restored To", style="bold green")

        for current, restored in reverted:
            table.add_row(Path(current).name, Path(restored).name)

        console.print(table)
        console.print(f"[bold green]Successfully restored {len(reverted)} files.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Undo failed:[/bold red] {e}")
        raise click.Abort()


if __name__ == "__main__":
    cli()
