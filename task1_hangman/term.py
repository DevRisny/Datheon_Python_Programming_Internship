"""Small terminal styling helpers (colours, boxes, tables) built on the standard library only.

Colours turn off automatically when output is not a terminal, when NO_COLOR is set,
or when --no-color is passed, so logs and CSV-friendly output stay clean.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Old Windows consoles use a code page that cannot print ╭ █ ♥; switch our output to UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (getattr(_stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

_enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
if os.environ.get("FORCE_COLOR"):
    _enabled = True
if _enabled and os.name == "nt":  # turn on ANSI escape codes in the Windows console
    os.system("")

STYLES = {
    "bold": "1", "dim": "2", "italic": "3", "underline": "4",
    "red": "38;5;203", "green": "38;5;35", "yellow": "38;5;178", "blue": "38;5;69",
    "cyan": "38;5;38", "magenta": "38;5;170", "grey": "38;5;245", "white": "97",
    "orange": "38;5;208", "teal": "38;5;30",
}


def set_color(enabled: bool) -> None:
    global _enabled
    _enabled = enabled


def color_enabled() -> bool:
    return _enabled


def style(text: object, *names: str) -> str:
    text = str(text)
    if not _enabled or not names:
        return text
    codes = ";".join(STYLES[n] for n in names if n in STYLES)
    return f"\x1b[{codes}m{text}\x1b[0m"


def strip(text: str) -> str:
    """Removes colour codes, e.g. to measure the visible width of a string."""
    return _ANSI.sub("", text)


def width() -> int:
    return max(60, min(shutil.get_terminal_size((80, 24)).columns, 100))


def pad(text: str, size: int, align: str = "<") -> str:
    gap = max(0, size - len(strip(text)))
    if align == ">":
        return " " * gap + text
    if align == "^":
        return " " * (gap // 2) + text + " " * (gap - gap // 2)
    return text + " " * gap


def box(lines: list[str], title: str = "", color: str = "cyan", size: int | None = None) -> str:
    """Draws a rounded box around the lines."""
    inner = size or max([len(strip(line)) for line in lines] + [len(title) + 2]) + 2
    top = "╭─" + (f" {title} " if title else "") + "─" * (inner - len(title) - (3 if title else 1)) + "╮"
    out = [style(top, color)]
    for line in lines:
        out.append(style("│", color) + " " + pad(line, inner - 2) + " " + style("│", color))
    out.append(style("╰" + "─" * inner + "╯", color))
    return "\n".join(out)


def rule(label: str = "", color: str = "grey") -> str:
    w = width()
    if not label:
        return style("─" * w, color)
    side = (w - len(label) - 2) // 2
    return style("─" * side, color) + " " + style(label, "bold") + " " + style("─" * (w - side - len(label) - 2), color)


def table(headers: list[str], rows: list[list[str]], align: str | None = None, color: str = "cyan") -> str:
    """A simple aligned table. align is one character per column: '<', '>' or '^'."""
    align = align or "<" * len(headers)
    widths = [max(len(strip(str(r[i]))) for r in [headers] + rows) for i in range(len(headers))]
    def fmt(row: list[str], bold: bool = False) -> str:
        cells = [pad(style(c, "bold") if bold else str(c), widths[i], align[i]) for i, c in enumerate(row)]
        return "  ".join(cells)
    out = [fmt(headers, bold=True), style("  ".join("─" * w for w in widths), color)]
    out += [fmt(r) for r in rows]
    return "\n".join(out)


def bar(fraction: float, size: int = 24, color: str = "blue") -> str:
    """A horizontal bar for 0..1, drawn with block characters."""
    fraction = max(0.0, min(1.0, fraction))
    full = int(fraction * size)
    part = "▏▎▍▌▋▊▉"[int((fraction * size - full) * 7)] if full < size and fraction * size - full > 0.07 else ""
    return style("█" * full + part, color) + style("·" * (size - full - len(part)), "grey")
