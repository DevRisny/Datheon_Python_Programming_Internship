"""Records scripted runs of the four programs and renders them as light-theme terminal
screenshots (PNG), animated demos (GIF) and video clips (MP4) for the README.

    python tools/record_demos.py            # writes docs/*.png, docs/*.gif and docs/clips/*.mp4

Needs Pillow and ffmpeg. The programs themselves use only the standard library.
"""
from __future__ import annotations

import builtins
import contextlib
import importlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
COLS, ROWS = 96, 36
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
FONT = ImageFont.truetype(FONT_DIR + "DejaVuSansMono.ttf", 15)
FONT_B = ImageFont.truetype(FONT_DIR + "DejaVuSansMono-Bold.ttf", 15)
TITLE_FONT = ImageFont.truetype("/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf", 14)
CW = round(FONT.getlength("M"))
CH = 21

# Light terminal theme: the program's 256-colour codes mapped to readable colours on white.
PALETTE = {"203": (214, 59, 74), "35": (16, 140, 92), "178": (176, 118, 0), "69": (49, 87, 235),
           "38": (8, 136, 178), "170": (176, 56, 172), "245": (128, 135, 160), "97": (17, 26, 58),
           "208": (214, 100, 10), "30": (14, 122, 124)}
INK = (29, 36, 64)
BG = (252, 253, 255)
EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-⛿✀-➿️]")
KEEP = set("♥♡✔✘▲▼■")


class Screen:
    """A tiny terminal emulator: handles text, newlines, \\r, colours and screen clears."""

    def __init__(self):
        self.lines: list[list[tuple[str, tuple, bool]]] = [[]]
        self.fg, self.bold = INK, False

    def clear(self):
        self.lines = [[]]

    def write(self, text: str):
        for part in re.split(r"(\x1b\[[0-9;]*m)", text):
            if part.startswith("\x1b["):
                codes = part[2:-1].split(";") if part[2:-1] else ["0"]
                i = 0
                while i < len(codes):
                    c = codes[i]
                    if c == "0":
                        self.fg, self.bold = INK, False
                    elif c == "1":
                        self.bold = True
                    elif c == "38" and i + 2 < len(codes):
                        self.fg = PALETTE.get(codes[i + 2], INK)
                        i += 2
                    elif c == "97":
                        self.fg = PALETTE["97"]
                    i += 1
                continue
            for ch in part:
                if ch in KEEP:
                    pass
                elif EMOJI.match(ch):
                    continue
                if ch == "\n":
                    self.lines.append([])
                elif ch == "\r":
                    self.lines[-1] = []
                elif ch == "\x0c":
                    self.clear()
                else:
                    if len(self.lines[-1]) >= COLS:
                        self.lines.append([])
                    self.lines[-1].append((ch, self.fg, self.bold))

    def visible(self):
        return self.lines[-ROWS:]


def draw(screen: Screen, title: str, cursor: bool = True) -> Image.Image:
    pad, bar = 22, 38
    w, h = COLS * CW + pad * 2, ROWS * CH + pad * 2 + bar
    win = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(win)
    d.rectangle([0, 0, w, bar], fill=(238, 242, 251))
    d.line([0, bar, w, bar], fill=(220, 226, 242))
    for i, color in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        d.ellipse([16 + i * 22, 13, 28 + i * 22, 25], fill=color)
    tw = d.textlength(title, font=TITLE_FONT)
    d.text(((w - tw) / 2, 10), title, font=TITLE_FONT, fill=(98, 106, 135))
    rows = screen.visible()
    for r, line in enumerate(rows):
        for c, (ch, fg, bold) in enumerate(line):
            if ch != " ":
                d.text((pad + c * CW, bar + pad + r * CH), ch, font=FONT_B if bold else FONT, fill=fg)
    if cursor:
        r = len(rows) - 1
        c = len(rows[-1]) if rows else 0
        d.rectangle([pad + c * CW, bar + pad + r * CH + 2, pad + c * CW + CW - 2, bar + pad + r * CH + 18],
                    fill=(49, 87, 255))
    return win


_BACKDROP: dict = {}


def framed(win: Image.Image) -> Image.Image:
    """Puts the window on a soft brand-coloured background with a shadow and rounded corners."""
    margin = 36
    W, H = win.width + margin * 2, win.height + margin * 2
    if (W, H) not in _BACKDROP:
        _BACKDROP[(W, H)] = _backdrop(win.size, margin)
    bg, mask = _BACKDROP[(W, H)]
    bg = bg.copy()
    bg.paste(win, (margin, margin), mask)
    ImageDraw.Draw(bg).rounded_rectangle([margin, margin, margin + win.width - 1, margin + win.height - 1],
                                         radius=12, outline=(214, 222, 245), width=1)
    return bg.convert("RGB")


def _backdrop(size, margin):
    w, h = size
    W, H = w + margin * 2, h + margin * 2
    bg = Image.new("RGB", (W, H))
    g = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        g.line([(0, y), (W, y)], fill=(int(232 + 8 * t), int(239 + 6 * t), 255))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([margin, margin + 10, margin + w, margin + h + 10],
                                             radius=14, fill=(49, 87, 255, 60))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=255)
    return bg, mask


class Recorder:
    """Collects (frame, seconds) pairs while a program runs with scripted keyboard input."""

    def __init__(self, title: str, command: str):
        self.title = title
        self.screen = Screen()
        self.frames: list[tuple[Image.Image, float]] = []
        self.type_line(command, prompt="$ ")

    def snap(self, seconds: float, cursor: bool = True):
        self.frames.append((framed(draw(self.screen, self.title, cursor)), seconds))

    def type_line(self, text: str, prompt: str = ""):
        if prompt:
            self.screen.write("\x1b[38;5;35m" + prompt + "\x1b[0m")
        for i in range(0, len(text), 2):
            self.screen.write(text[i:i + 2])
            self.snap(0.06)
        self.snap(0.35)
        self.screen.write("\n")

    def output(self, text: str):
        self.screen.write(text)


def run(module_dir: str, module: str, argv: list[str], answers: list[str], title: str, command: str,
        cwd: Path | None = None, clears: bool = False, pause_after: float = 1.2,
        size: tuple[int, int] = (96, 36)) -> Recorder:
    global COLS, ROWS
    COLS, ROWS = size
    os.environ["COLUMNS"] = str(COLS)
    rec = Recorder(title, command)
    folder = ROOT / module_dir
    sys.path.insert(0, str(folder))
    for name in [module, "term"] + [m for m in list(sys.modules) if m.endswith(("_core", "_art", "_stats"))]:
        sys.modules.pop(name, None)
    os.environ["FORCE_COLOR"] = "1"
    os.environ.pop("NO_COLOR", None)
    mod = importlib.import_module(module)
    term = sys.modules["term"]
    term.set_color(True)
    queue = list(answers)

    class Out(io.TextIOBase):
        def write(self, s):
            if s:
                rec.output(s)
                if "\n" in s:
                    rec.snap(0.03)
            return len(s)

    def fake_input(prompt=""):
        rec.output(prompt)
        rec.snap(0.5)
        if not queue:
            raise EOFError
        answer = queue.pop(0)
        rec.type_line(answer)
        return answer

    old_cwd = Path.cwd()
    if cwd:
        os.chdir(cwd)
    if clears and hasattr(mod, "clear"):
        mod.clear = lambda enabled: (rec.snap(pause_after), rec.screen.clear())
    try:
        with contextlib.redirect_stdout(Out()):
            original = builtins.input
            builtins.input = fake_input
            try:
                mod.main(argv)
            finally:
                builtins.input = original
    finally:
        os.chdir(old_cwd)
        sys.path.remove(str(folder))
    rec.snap(3.0, cursor=False)
    return rec


def merge_short_frames(frames):
    """Combines very short frames so GIFs stay small without losing the motion."""
    out, acc = [], 0.0
    for i, (img, sec) in enumerate(frames):
        acc += sec
        last = i == len(frames) - 1
        if acc >= 0.06 or last:
            out.append((img, round(acc, 2)))
            acc = 0.0
    return out


def export(rec: Recorder, name: str, still_index: int = -1):
    DOCS.mkdir(exist_ok=True)
    (DOCS / "clips").mkdir(exist_ok=True)
    frames = merge_short_frames(rec.frames)
    frames[still_index][0].save(DOCS / f"{name}.png", optimize=True)
    tmp = Path(tempfile.mkdtemp())
    lines = []
    for i, (img, sec) in enumerate(frames):
        p = tmp / f"f{i:04d}.png"
        img.save(p)
        lines.append(f"file '{p}'\nduration {sec}\n")
    lines.append(f"file '{tmp / f'f{len(frames) - 1:04d}.png'}'\n")
    (tmp / "list.txt").write_text("".join(lines))
    gif_scale = 760
    q = ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt")]
    subprocess.run(["ffmpeg", *q, "-vf", f"scale={gif_scale}:-1:flags=lanczos,palettegen=max_colors=96:stats_mode=diff",
                    str(tmp / "pal.png")], check=True)
    subprocess.run(["ffmpeg", *q, "-i", str(tmp / "pal.png"), "-lavfi",
                    f"scale={gif_scale}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle",
                    str(DOCS / f"{name}.gif")], check=True)
    subprocess.run(["ffmpeg", *q, "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(DOCS / "clips" / f"{name}.mp4")],
                   check=True)
    shutil.rmtree(tmp)
    print(f"{name}: {len(frames)} frames, gif {(DOCS / f'{name}.gif').stat().st_size // 1024} KB")


def main():
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        rec = run("task1_hangman", "hangman",
                  ["-c", "programming", "-d", "easy", "--seed", "4", "--stats-file", str(work / "s.json")],
                  ["e", "z", "a", "e", "?", "n", "!python", "n"],
                  "Task 1 · Hangman", "python hangman.py -c programming -d easy", clears=True, size=(84, 34))
        export(rec, "demo_task1_hangman", still_index=-12)

        rec = run("task2_portfolio", "portfolio", ["--demo", "--out", str(work)], [],
                  "Task 2 · Stock Portfolio Tracker", "python portfolio.py --demo", size=(106, 50))
        export(rec, "demo_task2_portfolio")

        rec = run("task3_file_organizer", "organizer", ["--demo"], [],
                  "Task 3 · File Organizer", "python organizer.py --demo", cwd=work, size=(90, 46))
        export(rec, "demo_task3_organizer")

        rec = run("task4_chatbot", "chatbot", ["--fast"],
                  ["hi", "my name is Risny", "How do I submit my project and is it free?", "more",
                   "certficate", "thanks dex", "bye"],
                  "Task 4 · Dex chatbot", "python chatbot.py", size=(110, 44))
        export(rec, "demo_task4_chatbot")


if __name__ == "__main__":
    main()
