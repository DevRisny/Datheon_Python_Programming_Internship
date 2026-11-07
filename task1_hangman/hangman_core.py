"""Hangman game rules, kept free of any input/output so they are easy to test."""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MAX_MISTAKES = 6
LETTERS = set(string.ascii_lowercase)


class Outcome(Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    REPEAT = "repeat"        # already guessed: no penalty
    INVALID = "invalid"      # not a single letter a-z
    WORD_CORRECT = "word_correct"
    WORD_WRONG = "word_wrong"
    OVER = "over"            # the game has already ended


@dataclass
class HangmanGame:
    """One round of Hangman. Spaces and punctuation in the secret are shown from the start."""

    secret: str
    category: str = ""
    max_mistakes: int = MAX_MISTAKES
    correct: set[str] = field(default_factory=set)
    wrong: list[str] = field(default_factory=list)
    hints_used: int = 0
    solved_by_word: bool = False

    def __post_init__(self) -> None:
        self.secret = " ".join(self.secret.lower().split())
        if not any(ch in LETTERS for ch in self.secret):
            raise ValueError("The secret word needs at least one letter a-z")

    # ----- state -----
    @property
    def mistakes(self) -> int:
        return len(self.wrong)

    @property
    def lives_left(self) -> int:
        return max(0, self.max_mistakes - self.mistakes)

    @property
    def letters_needed(self) -> set[str]:
        return {ch for ch in self.secret if ch in LETTERS}

    @property
    def won(self) -> bool:
        return self.solved_by_word or self.letters_needed <= self.correct

    @property
    def lost(self) -> bool:
        return not self.won and self.mistakes >= self.max_mistakes

    @property
    def over(self) -> bool:
        return self.won or self.lost

    @property
    def guessed(self) -> list[str]:
        """Every letter tried so far, in alphabetical order."""
        return sorted(self.correct | {w for w in self.wrong if w in LETTERS})

    @property
    def wrong_letters(self) -> list[str]:
        """Wrong letters in the order they were tried (hints and wrong word guesses left out)."""
        return [w for w in self.wrong if w in LETTERS]

    def masked(self) -> str:
        """'_ A _ H E O N' style view. Words are separated by three spaces."""
        words = []
        for word in self.secret.split(" "):
            shown = [ch.upper() if (ch not in LETTERS or ch in self.correct or self.over) else "_" for ch in word]
            words.append(" ".join(shown))
        return "   ".join(words)

    # ----- moves -----
    def guess(self, raw: str) -> Outcome:
        if self.over:
            return Outcome.OVER
        letter = raw.strip().lower()
        if len(letter) != 1 or letter not in LETTERS:
            return Outcome.INVALID
        if letter in self.correct or letter in self.wrong:
            return Outcome.REPEAT
        if letter in self.secret:
            self.correct.add(letter)
            return Outcome.CORRECT
        self.wrong.append(letter)
        return Outcome.WRONG

    def guess_word(self, raw: str) -> Outcome:
        """Guess the whole answer. A wrong guess costs one life, like a wrong letter."""
        if self.over:
            return Outcome.OVER
        attempt = " ".join(raw.lower().split())
        if not attempt or not any(ch in LETTERS for ch in attempt):
            return Outcome.INVALID
        if attempt == self.secret:
            self.solved_by_word = True
            self.correct |= self.letters_needed
            return Outcome.WORD_CORRECT
        self.wrong.append("*")  # counts as a mistake but is not a letter
        return Outcome.WORD_WRONG

    def hint(self, rng: random.Random | None = None) -> str | None:
        """Reveals one hidden letter for the cost of one life. Not allowed on the last life."""
        hidden = sorted(self.letters_needed - self.correct)
        if self.over or not hidden or self.lives_left <= 1:
            return None
        letter = (rng or random).choice(hidden)
        self.correct.add(letter)
        self.hints_used += 1
        self.wrong.append("?")  # the hint's cost
        return letter

    def score(self) -> int:
        """Points for a win: longer words and lives left score more, hints cost points."""
        if not self.won:
            return 0
        base = 10 * len(self.letters_needed) + 25 * self.lives_left
        bonus = 50 if self.solved_by_word else 0
        return max(10, base + bonus - 30 * self.hints_used)


# ----- word bank -----
DIFFICULTY = {"easy": (3, 6), "medium": (7, 9), "hard": (10, 99), "any": (1, 99)}


def letter_count(word: str) -> int:
    return sum(ch in LETTERS for ch in word)


def load_words(path: Path) -> list[str]:
    """Reads one word or phrase per line. Blank lines and # comments are skipped."""
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#") and any(ch in LETTERS for ch in line):
            if all(ch in LETTERS or ch in " -'" for ch in line):
                words.append(line)
    return words


def load_bank(folder: Path) -> dict[str, list[str]]:
    """Every .txt file in the folder is a category, named after the file."""
    bank = {}
    for file in sorted(folder.glob("*.txt")):
        words = load_words(file)
        if words:
            bank[file.stem.replace("_", " ").title()] = words
    return bank


def pick_word(words: list[str], difficulty: str = "any", rng: random.Random | None = None) -> str:
    low, high = DIFFICULTY.get(difficulty, DIFFICULTY["any"])
    choices = [w for w in words if low <= letter_count(w) <= high] or words
    return (rng or random).choice(choices)
