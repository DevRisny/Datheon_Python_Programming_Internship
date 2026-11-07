"""Keeps a small scoreboard between games in a JSON file."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Stats:
    played: int = 0
    won: int = 0
    streak: int = 0
    best_streak: int = 0
    best_score: int = 0
    total_score: int = 0

    @property
    def win_rate(self) -> float:
        return self.won / self.played if self.played else 0.0

    def record(self, won: bool, score: int) -> None:
        self.played += 1
        if won:
            self.won += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            self.best_score = max(self.best_score, score)
            self.total_score += score
        else:
            self.streak = 0


def load(path: Path) -> Stats:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Stats(**{k: int(v) for k, v in data.items() if k in Stats.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return Stats()  # first game, or an unreadable file: start fresh


def save(stats: Stats, path: Path) -> None:
    try:
        path.write_text(json.dumps(asdict(stats), indent=2), encoding="utf-8")
    except OSError:
        pass  # the game still works if the scoreboard cannot be saved
