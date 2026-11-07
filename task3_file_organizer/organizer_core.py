"""Plans and performs the file moves. No printing here: every rule is unit tested."""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CATEGORIES: dict[str, set[str]] = {
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".tex", ".epub"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".heic", ".tiff", ".ico", ".raw"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"},
    "Audio": {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz"},
    "Code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".html", ".css", ".php", ".json",
             ".xml", ".yml", ".yaml", ".sql", ".ipynb", ".kt", ".go", ".rb", ".sh", ".bat", ".ps1"},
    "Installers": {".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"},
    "Fonts": {".ttf", ".otf", ".woff", ".woff2"},
}
OTHERS = "Others"
EXTENSION_MAP = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}

# Files that must never be moved: unfinished downloads, system files and our own records.
PARTIAL_DOWNLOADS = {".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload"}
SYSTEM_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}
UNDO_FILE = ".organizer_undo.json"
LOG_FILE = "organizer.log"


def extension(path: Path) -> str:
    """Lower-case extension, keeping double ones like '.tar.gz'."""
    suffixes = [s.lower() for s in path.suffixes[-2:]]
    double = "".join(suffixes)
    if len(suffixes) == 2 and double in EXTENSION_MAP:
        return double
    return path.suffix.lower()


def category_for(path: Path) -> str:
    return EXTENSION_MAP.get(extension(path), OTHERS)


def skip_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name in SYSTEM_FILES:
        return "system file"
    if name in {UNDO_FILE, LOG_FILE}:
        return "organizer record"
    if name.startswith("."):
        return "hidden file"
    if path.suffix.lower() in PARTIAL_DOWNLOADS or name.startswith("~$"):
        return "download or file still in use"
    return None


def unique_destination(folder: Path, name: str, taken: set[Path] | None = None) -> Path:
    """'report.pdf' -> 'report (1).pdf' when the name is already used."""
    taken = taken or set()
    candidate = folder / name
    if not candidate.exists() and candidate not in taken:
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    if name.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        stem, suffix = name[: -len("".join(Path(name).suffixes[-2:]))], "".join(Path(name).suffixes[-2:])
    n = 1
    while True:
        candidate = folder / f"{stem} ({n}){suffix}"
        if not candidate.exists() and candidate not in taken:
            return candidate
        n += 1


@dataclass
class Move:
    source: Path
    target: Path
    category: str
    size: int


@dataclass
class Plan:
    folder: Path
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    def by_category(self) -> dict[str, tuple[int, int]]:
        """Category -> (number of files, total bytes), biggest first."""
        summary: dict[str, list[int]] = {}
        for m in self.moves:
            entry = summary.setdefault(m.category, [0, 0])
            entry[0] += 1
            entry[1] += m.size
        return {k: (v[0], v[1]) for k, v in sorted(summary.items(), key=lambda kv: (-kv[1][0], kv[0]))}


@dataclass
class Result:
    moved: list[Move] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    dry_run: bool = False


def make_plan(folder: Path) -> Plan:
    """Looks at every file directly inside the folder (with os.scandir) and decides where it goes."""
    folder = folder.resolve()
    plan = Plan(folder)
    taken: set[Path] = set()
    category_names = set(CATEGORIES) | {OTHERS}
    with os.scandir(folder) as entries:
        for entry in sorted(entries, key=lambda e: e.name.lower()):
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                continue  # sub-folders, including our category folders, are left alone
            if entry.is_symlink():
                plan.skipped.append((path, "shortcut / symbolic link"))
                continue
            reason = skip_reason(path)
            if reason:
                plan.skipped.append((path, reason))
                continue
            category = category_for(path)
            if category not in category_names:
                category = OTHERS
            target = unique_destination(folder / category, path.name, taken)
            taken.add(target)
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            plan.moves.append(Move(path, target, category, size))
    return plan


def get_logger(folder: Path) -> logging.Logger:
    logger = logging.getLogger(f"organizer.{folder}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        try:
            handler = logging.FileHandler(folder / LOG_FILE, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S"))
            logger.addHandler(handler)
        except OSError:
            logger.addHandler(logging.NullHandler())
    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def execute(plan: Plan, dry_run: bool = False, on_move=None) -> Result:
    """Moves the files with shutil.move. Problems with one file never stop the others."""
    result = Result(dry_run=dry_run)
    if dry_run:
        result.moved = list(plan.moves)
        return result
    logger = get_logger(plan.folder)
    logger.info("Organizing %s (%d files)", plan.folder, len(plan.moves))
    for move in plan.moves:
        try:
            move.target.parent.mkdir(exist_ok=True)
            if move.target.exists():  # appeared after planning: pick a fresh name
                move.target = unique_destination(move.target.parent, move.source.name)
            shutil.move(str(move.source), str(move.target))
            result.moved.append(move)
            logger.info("MOVED  %s -> %s/%s", move.source.name, move.category, move.target.name)
        except PermissionError:
            result.errors.append((move.source, "permission denied (file open or protected)"))
            logger.warning("SKIP   %s: permission denied", move.source.name)
        except FileNotFoundError:
            result.errors.append((move.source, "file disappeared before it could be moved"))
            logger.warning("SKIP   %s: file not found", move.source.name)
        except (FileExistsError, OSError) as error:
            result.errors.append((move.source, str(error)))
            logger.error("ERROR  %s: %s", move.source.name, error)
        if on_move:
            on_move(move)
    for path, reason in plan.skipped:
        logger.info("KEPT   %s (%s)", path.name, reason)
    logger.info("Done: %d moved, %d kept, %d errors", len(result.moved), len(plan.skipped), len(result.errors))
    close_logger(logger)
    if result.moved:
        save_undo(plan.folder, result.moved)
    return result


def save_undo(folder: Path, moves: list[Move]) -> None:
    record = {"created": datetime.now().isoformat(timespec="seconds"),
              "moves": [{"from": str(m.source), "to": str(m.target)} for m in moves]}
    (folder / UNDO_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")


def undo(folder: Path) -> tuple[int, list[str]]:
    """Puts every file from the last run back where it was, then removes empty category folders."""
    folder = folder.resolve()
    record_file = folder / UNDO_FILE
    if not record_file.exists():
        return 0, ["There is nothing to undo in this folder."]
    record = json.loads(record_file.read_text(encoding="utf-8"))
    restored, problems = 0, []
    for item in reversed(record.get("moves", [])):
        src, dst = Path(item["to"]), Path(item["from"])
        try:
            if not src.exists():
                problems.append(f"{src.name}: no longer in {src.parent.name}")
                continue
            target = dst if not dst.exists() else unique_destination(dst.parent, dst.name)
            shutil.move(str(src), str(target))
            restored += 1
        except OSError as error:
            problems.append(f"{src.name}: {error}")
    for name in list(CATEGORIES) + [OTHERS]:
        sub = folder / name
        if sub.is_dir() and not any(sub.iterdir()):
            sub.rmdir()
    record_file.unlink()
    log = get_logger(folder)
    log.info("UNDO   restored %d files", restored)
    close_logger(log)
    return restored, problems


def is_unsafe_target(folder: Path) -> str | None:
    """Refuses folders where moving files could break the computer."""
    folder = folder.resolve()
    if folder == Path(folder.anchor):
        return "a whole drive"
    if folder == Path.home().resolve():
        return "your home folder itself (choose Downloads or Desktop instead)"
    system = [Path("/bin"), Path("/etc"), Path("/usr"), Path("/System"), Path("/Library"),
              Path(os.environ.get("SystemRoot", r"C:\Windows")), Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    for path in system:
        try:
            if folder == path.resolve() or path.resolve() in folder.parents:
                return f"a system folder ({path})"
        except OSError:
            continue
    return None


def human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
