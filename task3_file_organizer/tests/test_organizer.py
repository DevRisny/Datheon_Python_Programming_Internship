import json
import shutil
from pathlib import Path

import pytest

import organizer as app
from organizer_core import (UNDO_FILE, category_for, execute, extension, human_size, is_unsafe_target,
                            make_plan, skip_reason, undo, unique_destination)


def touch(folder: Path, *names: str, size: int = 10) -> None:
    for name in names:
        (folder / name).write_bytes(b"x" * size)


@pytest.mark.parametrize("name,category", [
    ("Report.PDF", "Documents"), ("photo.jpeg", "Images"), ("clip.MP4", "Videos"), ("song.mp3", "Audio"),
    ("backup.tar.gz", "Archives"), ("main.py", "Code"), ("sheet.xlsx", "Spreadsheets"),
    ("deck.pptx", "Presentations"), ("setup.exe", "Installers"), ("font.ttf", "Fonts"),
    ("mystery.xyz", "Others"), ("README", "Others"), ("v1.2.notes.txt", "Documents"),
])
def test_categories(name, category):
    assert category_for(Path(name)) == category


def test_double_extension():
    assert extension(Path("data.tar.gz")) == ".tar.gz"
    assert extension(Path("my.photo.JPG")) == ".jpg"


@pytest.mark.parametrize("name", ["movie.mp4.crdownload", "file.part", "~$Draft.docx", ".env", "desktop.ini",
                                  UNDO_FILE, "organizer.log"])
def test_files_that_are_never_moved(name):
    assert skip_reason(Path(name)) is not None


def test_plan_and_move(tmp_path):
    touch(tmp_path, "a.pdf", "b.jpg", "c.py", "d.zip", "e.unknown", "f.mp4.crdownload")
    (tmp_path / "SubFolder").mkdir()
    plan = make_plan(tmp_path)
    assert len(plan.moves) == 5
    assert [p.name for p, _ in plan.skipped] == ["f.mp4.crdownload"]
    result = execute(plan)
    assert not result.errors
    assert (tmp_path / "Documents" / "a.pdf").exists()
    assert (tmp_path / "Images" / "b.jpg").exists()
    assert (tmp_path / "Code" / "c.py").exists()
    assert (tmp_path / "Archives" / "d.zip").exists()
    assert (tmp_path / "Others" / "e.unknown").exists()
    assert (tmp_path / "f.mp4.crdownload").exists()   # unfinished download left alone
    assert (tmp_path / "SubFolder").is_dir()           # folders are not touched
    assert "MOVED  a.pdf -> Documents/a.pdf" in (tmp_path / "organizer.log").read_text(encoding="utf-8")


def test_name_clash_never_overwrites(tmp_path):
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents" / "notes.txt").write_text("old", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("new", encoding="utf-8")
    execute(make_plan(tmp_path))
    assert (tmp_path / "Documents" / "notes.txt").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "Documents" / "notes (1).txt").read_text(encoding="utf-8") == "new"


def test_unique_name_keeps_double_extension(tmp_path):
    touch(tmp_path, "data.tar.gz")
    assert unique_destination(tmp_path, "data.tar.gz").name == "data (1).tar.gz"


def test_dry_run_changes_nothing(tmp_path):
    touch(tmp_path, "a.pdf", "b.jpg")
    result = execute(make_plan(tmp_path), dry_run=True)
    assert len(result.moved) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "b.jpg"]


def test_permission_error_is_reported_and_others_still_move(tmp_path, monkeypatch):
    touch(tmp_path, "locked.pdf", "free.jpg")
    real_move = shutil.move

    def fake_move(src, dst):
        if src.endswith("locked.pdf"):
            raise PermissionError("in use")
        return real_move(src, dst)

    monkeypatch.setattr(shutil, "move", fake_move)
    result = execute(make_plan(tmp_path))
    assert [p.name for p, _ in result.errors] == ["locked.pdf"]
    assert (tmp_path / "Images" / "free.jpg").exists()
    assert (tmp_path / "locked.pdf").exists()


def test_undo_restores_everything(tmp_path):
    touch(tmp_path, "a.pdf", "b.jpg", "c.py")
    execute(make_plan(tmp_path))
    record = json.loads((tmp_path / UNDO_FILE).read_text(encoding="utf-8"))
    assert len(record["moves"]) == 3
    restored, problems = undo(tmp_path)
    assert restored == 3 and problems == []
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["a.pdf", "b.jpg", "c.py", "organizer.log"]   # category folders removed again


def test_undo_with_nothing_to_undo(tmp_path):
    restored, problems = undo(tmp_path)
    assert restored == 0 and problems


def test_refuses_dangerous_folders():
    assert is_unsafe_target(Path(Path.cwd().anchor)) is not None
    assert is_unsafe_target(Path.home()) is not None


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"


def test_demo_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert app.main(["--demo", "--no-color"]) == 0
    out = capsys.readouterr().out
    demo = tmp_path / "demo_downloads"
    assert "Name clashes handled" in out and "notes (1).txt" in out
    assert (demo / "Images" / "screenshot.png").exists()
    assert (demo / "big_movie.mp4.crdownload").exists()
    assert app.main([str(demo), "--undo", "--no-color"]) == 0
    assert (demo / "screenshot.png").exists()


def test_cli_dry_run_and_cancel(tmp_path, monkeypatch, capsys):
    touch(tmp_path, "a.pdf")
    assert app.main([str(tmp_path), "--dry-run", "--no-color"]) == 0
    assert "This was a preview" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert app.main([str(tmp_path), "--no-color"]) == 0
    assert "Nothing was moved" in capsys.readouterr().out
    assert (tmp_path / "a.pdf").exists()


def test_missing_folder(tmp_path, capsys):
    assert app.main([str(tmp_path / "nope"), "--no-color"]) == 1
