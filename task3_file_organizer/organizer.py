#!/usr/bin/env python3
"""
Automated File Organizer & Cleanup Utility.

Sorts a messy folder (like Downloads) into Documents, Images, Videos, Archives, Code and more.
It previews the plan first, never overwrites a file, skips files that are still downloading,
logs every move to organizer.log, and can undo the last run.

    python organizer.py                     # organize your Downloads folder (asks before moving)
    python organizer.py "D:\\My Files" --dry-run   # only show what would happen
    python organizer.py --demo              # try it safely on a sample messy folder
    python organizer.py ~/Downloads --undo  # put everything back

Datheon Python Programming Internship · Task 3 · J. Risny Suha
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import term
from organizer_core import (CATEGORIES, LOG_FILE, OTHERS, Plan, Result, execute, human_size, is_unsafe_target,
                            make_plan, undo)
from term import style

COLORS = {"Documents": "blue", "Spreadsheets": "green", "Presentations": "orange", "Images": "magenta",
          "Videos": "red", "Audio": "cyan", "Archives": "yellow", "Code": "teal", "Installers": "grey",
          "Fonts": "grey", OTHERS: "grey"}

DEMO_FILES = [
    "Internship_Offer_Letter.pdf", "CV_J_Risny_Suha.docx", "notes.txt", "Lecture 05 - Networking.pdf",
    "budget_2026.xlsx", "attendance.csv", "Final_Presentation.pptx", "IMG_20261104_101522.jpg",
    "IMG_20261104_101522 (copy).jpg", "screenshot.png", "logo.svg", "campus_tour.mp4", "lecture_recording.mkv",
    "podcast_episode_12.mp3", "voice_note.m4a", "project_backup.zip", "dataset.tar.gz", "photos.rar",
    "hangman.py", "index.html", "styles.css", "config.json", "python-3.13.0-amd64.exe", "app-release.apk",
    "Poppins-Bold.ttf", "random_file.xyz", "README", "big_movie.mp4.crdownload", "~$Draft.docx", ".hidden_settings",
]


def make_demo(folder: Path) -> Path:
    """Creates a messy sample folder to try the organizer without touching real files."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    for name in DEMO_FILES:
        (folder / name).write_bytes(b"x" * rng.randint(2_000, 900_000))
    (folder / "Documents").mkdir(exist_ok=True)
    (folder / "Documents" / "notes.txt").write_text("an older notes.txt already sorted here", encoding="utf-8")
    return folder


def preview(plan: Plan) -> str:
    rows = []
    total_size = sum(m.size for m in plan.moves)
    for category, (count, size) in plan.by_category().items():
        share = size / total_size if total_size else 0
        rows.append([f"{style('■', COLORS.get(category, 'grey'))} {style(category, 'bold')}",
                     str(count), human_size(size), term.bar(share, 18, COLORS.get(category, "blue"))])
    lines = [term.rule(f"PLAN FOR {plan.folder.name or plan.folder}".upper()), ""]
    if rows:
        lines.append(term.table(["Category", "Files", "Size", "Share of size"], rows, "<>><"))
    else:
        lines.append(style("  Nothing to organize: no loose files found.", "green"))
    renamed = [m for m in plan.moves if m.target.name != m.source.name]
    if renamed:
        lines.append("")
        lines.append(style("  Name clashes handled (nothing is overwritten):", "bold"))
        for m in renamed:
            lines.append(f"    {m.source.name}  →  {m.category}/{style(m.target.name, 'yellow')}")
    if plan.skipped:
        lines.append("")
        lines.append(style(f"  Left in place ({len(plan.skipped)}):", "bold"))
        for path, reason in plan.skipped:
            lines.append(style(f"    {path.name}  ·  {reason}", "grey"))
    return "\n".join(lines)


def summary(result: Result, plan: Plan, seconds: float) -> str:
    moved_size = sum(m.size for m in result.moved)
    verb = "Would move" if result.dry_run else "Moved"
    color = "yellow" if result.dry_run else ("green" if not result.errors else "orange")
    body = [f"{verb:<12} {style(str(len(result.moved)), 'bold')} files  ({human_size(moved_size)})",
            f"{'Left alone':<12} {len(plan.skipped)} files",
            f"{'Problems':<12} {style(str(len(result.errors)), 'bold', 'red' if result.errors else 'green')}",
            f"{'Time':<12} {seconds:.2f} s"]
    for path, reason in result.errors:
        body.append(style(f"  ✘ {path.name}: {reason}", "red"))
    if result.dry_run:
        body += ["", "This was a preview. Run again without --dry-run to move the files."]
    else:
        body += ["", f"Every move is written to {LOG_FILE} in that folder.",
                 "Changed your mind? Run the same command with --undo."]
    return term.box(body, title="Dry run" if result.dry_run else "Done", color=color)


def confirm(question: str) -> bool:
    try:
        return input(style(question, "cyan", "bold")).strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Organize a folder into category sub-folders.")
    parser.add_argument("folder", nargs="?", type=Path, default=Path.home() / "Downloads",
                        help="folder to organize (default: your Downloads folder)")
    parser.add_argument("--dry-run", action="store_true", help="show the plan without moving anything")
    parser.add_argument("--undo", action="store_true", help="put back the files moved by the last run")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--demo", action="store_true", help="create a messy sample folder and organize it")
    parser.add_argument("--no-color", action="store_true", help="plain text output")
    args = parser.parse_args(argv)
    if args.no_color:
        term.set_color(False)

    folder = args.folder.expanduser()
    if args.demo:
        folder = make_demo(Path.cwd() / "demo_downloads")
        print(style(f"Created a messy sample folder: {folder}", "grey"))
    if not folder.is_dir():
        print(style(f"✘ Folder not found: {folder}", "red"))
        return 1
    danger = is_unsafe_target(folder)
    if danger:
        print(style(f"✘ For safety, the organizer will not touch {danger}.", "red"))
        return 2

    print(term.box([style("Automated File Organizer", "bold"),
                    f"Folder: {folder.resolve()}"], color="blue"))

    if args.undo:
        restored, problems = undo(folder)
        for problem in problems:
            print(style(f"  • {problem}", "yellow"))
        print(style(f"✔ Restored {restored} files to {folder.name}.", "green") if restored else "")
        return 0

    start = time.perf_counter()
    try:
        plan = make_plan(folder)
    except PermissionError:
        print(style(f"✘ No permission to read {folder}.", "red"))
        return 1
    print(preview(plan))
    print()
    if not plan.moves:
        return 0
    if not args.dry_run and not (args.yes or args.demo):
        if not confirm(f"Move {len(plan.moves)} files into category folders? (y/n) › "):
            print(style("Nothing was moved.", "yellow"))
            return 0

    done = 0

    def progress(_move):
        nonlocal done
        done += 1
        if sys.stdout.isatty():
            print(f"\r  {term.bar(done / len(plan.moves), 30, 'green')} {done}/{len(plan.moves)}", end="", flush=True)

    result = execute(plan, dry_run=args.dry_run, on_move=progress)
    if sys.stdout.isatty() and not args.dry_run:
        print()
    print(summary(result, plan, time.perf_counter() - start))
    return 0 if not result.errors else 3


if __name__ == "__main__":
    sys.exit(main())
