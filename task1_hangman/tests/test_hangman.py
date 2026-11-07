import random
from pathlib import Path

import pytest

import hangman
import hangman_stats
from hangman_art import STAGES, gallows
from hangman_core import HangmanGame, Outcome, letter_count, load_bank, load_words, pick_word

WORDS = Path(__file__).resolve().parent.parent / "words"


def test_masked_word_shows_only_found_letters():
    game = HangmanGame("datheon")
    game.guess("a")
    game.guess("h")
    assert game.masked() == "_ A _ H _ _ _"


def test_correct_and_wrong_guesses():
    game = HangmanGame("python")
    assert game.guess("P") is Outcome.CORRECT
    assert game.guess("z") is Outcome.WRONG
    assert game.mistakes == 1
    assert game.lives_left == 5


def test_repeated_letter_costs_nothing():
    game = HangmanGame("python")
    game.guess("z")
    assert game.guess("z") is Outcome.REPEAT
    assert game.guess("p") is Outcome.CORRECT
    assert game.guess("P") is Outcome.REPEAT
    assert game.mistakes == 1


@pytest.mark.parametrize("raw", ["", "ab", "1", "@", " "])
def test_invalid_input_is_rejected_without_penalty(raw):
    game = HangmanGame("python")
    assert game.guess(raw) is Outcome.INVALID
    assert game.mistakes == 0


def test_six_wrong_guesses_lose_the_game():
    game = HangmanGame("cat")
    for letter in "bdefgh":
        game.guess(letter)
    assert game.lost and game.over and not game.won
    assert game.guess("c") is Outcome.OVER
    assert game.masked() == "C A T"  # revealed at the end


def test_finding_every_letter_wins():
    game = HangmanGame("level")
    for letter in "lev":
        game.guess(letter)
    assert game.won and game.score() > 0


def test_phrases_show_spaces_from_the_start():
    game = HangmanGame("Sri  Lanka")
    assert game.secret == "sri lanka"
    assert game.masked() == "_ _ _   _ _ _ _ _"


def test_guess_whole_word():
    game = HangmanGame("sri lanka")
    assert game.guess_word("Sri Lanka") is Outcome.WORD_CORRECT
    assert game.won and game.solved_by_word


def test_wrong_whole_word_costs_a_life():
    game = HangmanGame("python")
    assert game.guess_word("java") is Outcome.WORD_WRONG
    assert game.mistakes == 1
    assert game.wrong_letters == []


def test_hint_reveals_a_letter_for_a_life():
    game = HangmanGame("banana")
    letter = game.hint(random.Random(1))
    assert letter in {"b", "a", "n"}
    assert letter in game.correct
    assert game.lives_left == 5 and game.hints_used == 1


def test_no_hint_on_the_last_life():
    game = HangmanGame("banana")
    for letter in "cdefg":
        game.guess(letter)
    assert game.lives_left == 1
    assert game.hint() is None


def test_score_rewards_lives_and_penalises_hints():
    clean = HangmanGame("python")
    for ch in "python":
        clean.guess(ch)
    hinted = HangmanGame("python")
    hinted.hint(random.Random(0))
    for ch in "python":
        hinted.guess(ch)
    assert clean.score() > hinted.score() > 0


def test_secret_needs_a_letter():
    with pytest.raises(ValueError):
        HangmanGame("123")


def test_one_drawing_per_mistake():
    assert len(STAGES) == 7
    assert gallows(0) != gallows(6)
    assert gallows(99) == gallows(6)


def test_word_bank_loads_every_category():
    bank = load_bank(WORDS)
    assert {"Animals", "Countries", "Programming", "Fruits", "Sri Lanka"} <= set(bank)
    assert all(len(words) >= 15 for words in bank.values())


def test_word_list_skips_comments_and_bad_lines(tmp_path):
    file = tmp_path / "w.txt"
    file.write_text("# comment\n\nApple\nbad_word!\n42\nice cream\n", encoding="utf-8")
    assert load_words(file) == ["apple", "ice cream"]


def test_difficulty_filters_by_length():
    words = ["cat", "python", "algorithm", "polymorphism"]
    rng = random.Random(3)
    assert all(letter_count(pick_word(words, "hard", rng)) >= 10 for _ in range(20))
    assert all(3 <= letter_count(pick_word(words, "easy", rng)) <= 6 for _ in range(20))


def test_stats_track_streaks(tmp_path):
    path = tmp_path / "stats.json"
    stats = hangman_stats.load(path)
    stats.record(True, 120)
    stats.record(True, 90)
    stats.record(False, 0)
    hangman_stats.save(stats, path)
    again = hangman_stats.load(path)
    assert (again.played, again.won, again.streak, again.best_streak, again.best_score) == (3, 2, 0, 2, 120)


def test_broken_stats_file_starts_fresh(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text("not json", encoding="utf-8")
    assert hangman_stats.load(path).played == 0


def test_full_game_from_the_command_line(monkeypatch, capsys, tmp_path):
    answers = iter(["z", "z", "p", "?", "!python"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code = hangman.main(["--word", "python", "--no-color", "--no-clear", "--seed", "1",
                         "--stats-file", str(tmp_path / "s.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "already tried 'Z'" in out
    assert "You found PYTHON by guessing the whole word" in out


def test_quit_leaves_cleanly(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("builtins.input", lambda prompt="": "quit")
    assert hangman.main(["--word", "python", "--no-color", "--no-clear",
                         "--stats-file", str(tmp_path / "s.json")]) == 0
    assert "Thanks for playing" in capsys.readouterr().out
