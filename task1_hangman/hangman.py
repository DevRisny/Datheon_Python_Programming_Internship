#!/usr/bin/env python3
"""
Hangman: guess the hidden word one letter at a time before the gallows is complete.

    python hangman.py                      # choose a category and difficulty from the menu
    python hangman.py -c programming -d hard
    python hangman.py --wordlist words.txt # play with your own word list

Datheon Python Programming Internship · Task 1 · J. Risny Suha
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

import hangman_art as art
import hangman_stats
import term
from hangman_core import MAX_MISTAKES, HangmanGame, Outcome, load_bank, load_words, pick_word
from term import style

HERE = Path(__file__).resolve().parent
DEFAULT_STATS = Path.home() / ".hangman_stats.json"
DIFFICULTIES = ["easy", "medium", "hard"]


class Quit(Exception):
    """The player typed quit or closed the input."""


def ask(prompt: str) -> str:
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise Quit from None
    if answer.strip().lower() in {"quit", "exit", ":q"}:
        raise Quit
    return answer.strip()


def clear(enabled: bool) -> None:
    if enabled:
        os.system("cls" if os.name == "nt" else "clear")


def choose(title: str, options: list[str], default: int = 0) -> int:
    print(style(title, "bold"))
    for i, option in enumerate(options, 1):
        marker = style("›", "cyan") if i - 1 == default else " "
        print(f"  {marker} {style(str(i), 'cyan', 'bold')}  {option}")
    while True:
        raw = ask(style(f"  Choose 1-{len(options)} [{default + 1}]: ", "grey"))
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        matches = [i for i, o in enumerate(options) if o.lower().startswith(raw.lower())]
        if len(matches) == 1:
            return matches[0]
        print(style("  Please type a number from the list.", "yellow"))


def hearts(game: HangmanGame) -> str:
    return style("♥ " * game.lives_left, "red") + style("♡ " * game.mistakes, "grey")


def draw(game: HangmanGame, message: str = "") -> str:
    danger = "red" if game.lives_left <= 2 else "yellow" if game.lives_left <= 4 else "blue"
    lines = [style(art.gallows(game.mistakes), danger)]
    lines.append("")
    lines.append("   " + style(game.category.upper() or "CUSTOM WORD", "grey") +
                 style(f"  ·  {len(game.letters_needed)} different letters", "grey"))
    lines.append("")
    lines.append("   " + style(game.masked(), "bold", "white"))
    lines.append("")
    lines.append("   Lives  " + hearts(game) + style(f" {game.lives_left}/{game.max_mistakes}", "grey"))
    used = "  ".join(style(c.upper(), "green") if c in game.correct else style(c.upper(), "red")
                     for c in game.guessed)
    lines.append("   Tried  " + (used or style("nothing yet", "grey")))
    if message:
        lines.append("")
        lines.append("   " + message)
    return "\n".join(lines)


FEEDBACK = {
    Outcome.CORRECT: lambda g, x: style(f"✔ Yes! '{x.upper()}' is in the word.", "green"),
    Outcome.WRONG: lambda g, x: style(f"✘ No '{x.upper()}'. {g.lives_left} lives left.", "red"),
    Outcome.REPEAT: lambda g, x: style(f"You already tried '{x.upper()}'. No life lost, try another.", "yellow"),
    Outcome.INVALID: lambda g, x: style("Type one letter A-Z.  ? = hint   ! = guess the word   quit = leave", "yellow"),
    Outcome.WORD_WRONG: lambda g, x: style(f"✘ '{x}' is not it. That cost a life.", "red"),
}


def play_round(game: HangmanGame, rng: random.Random, clear_screen: bool) -> None:
    message = style("Guess a letter.  ? = hint (costs a life)   ! = guess the whole word", "grey")
    while not game.over:
        clear(clear_screen)
        print(draw(game, message))
        raw = ask(style("\n   Your guess › ", "cyan", "bold"))
        if raw == "?":
            letter = game.hint(rng)
            message = (style(f"Hint: the word has an '{letter.upper()}'. That cost one life.", "magenta")
                       if letter else style("No hint on your last life. You can do it!", "yellow"))
            continue
        if raw.startswith("!"):
            attempt = raw[1:].strip() or ask(style("   Your answer › ", "cyan"))
            outcome = game.guess_word(attempt)
            message = FEEDBACK.get(outcome, lambda g, x: "")(game, attempt)
            continue
        outcome = game.guess(raw)
        message = FEEDBACK.get(outcome, lambda g, x: "")(game, raw.strip()[:1])
    clear(clear_screen)
    print(draw(game))


def show_result(game: HangmanGame, stats: hangman_stats.Stats) -> None:
    print(style(art.WIN, "green", "bold") if game.won else style(art.LOSE, "red", "bold"))
    if game.won:
        how = "by guessing the whole word" if game.solved_by_word else "letter by letter"
        lines = [f"You found {style(game.secret.upper(), 'bold', 'green')} {how}.",
                 f"Score  {style('+' + str(game.score()), 'bold', 'green')}   "
                 f"lives left {game.lives_left}   hints {game.hints_used}"]
    else:
        lines = [f"The word was {style(game.secret.upper(), 'bold', 'red')}.",
                 "Shake it off and try another one!"]
    lines += ["",
              f"Played {stats.played}   Won {stats.won}   Win rate {stats.win_rate:.0%}",
              f"Streak {stats.streak}   Best streak {stats.best_streak}   Best score {stats.best_score}"]
    print(term.box(lines, title="Result", color="green" if game.won else "red"))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Console Hangman with ASCII gallows art.")
    parser.add_argument("-c", "--category", help="category name, e.g. animals, countries, programming")
    parser.add_argument("-d", "--difficulty", choices=DIFFICULTIES + ["any"], help="word length level")
    parser.add_argument("--wordlist", type=Path, help="your own word list: one word or phrase per line")
    parser.add_argument("--word", help="play a specific word (handy for teaching or testing)")
    parser.add_argument("--seed", type=int, help="random seed, to repeat the same words")
    parser.add_argument("--stats-file", type=Path, default=DEFAULT_STATS, help="where the scoreboard is saved")
    parser.add_argument("--no-clear", action="store_true", help="do not clear the screen between turns")
    parser.add_argument("--no-color", action="store_true", help="plain text output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.no_color:
        term.set_color(False)
    rng = random.Random(args.seed)
    clear_screen = sys.stdout.isatty() and not args.no_clear

    if args.wordlist:
        try:
            bank = {args.wordlist.stem.title(): load_words(args.wordlist)}
        except OSError as error:
            print(style(f"Could not read the word list: {error}", "red"))
            return 1
    else:
        bank = load_bank(HERE / "words")
    bank = {k: v for k, v in bank.items() if v}
    if not bank and not args.word:
        print(style("No words found. Add .txt files to the words/ folder.", "red"))
        return 1

    stats = hangman_stats.load(args.stats_file)
    clear(clear_screen)
    print(style(art.TITLE, "blue", "bold"))
    print(style("   Guess the word before the gallows is complete. You have 6 lives.\n", "grey"))

    try:
        while True:
            if args.word:
                game = HangmanGame(args.word, "custom word")
            else:
                names = list(bank)
                if args.category:
                    match = [n for n in names if n.lower().replace(" ", "") == args.category.lower().replace("_", "").replace(" ", "")]
                    category = match[0] if match else names[0]
                else:
                    category = names[choose("Pick a category", names + ["Surprise me"], len(names))] \
                        if len(names) > 1 else names[0]
                    if category == "Surprise me":
                        category = rng.choice(names)
                difficulty = args.difficulty or DIFFICULTIES[choose(
                    "\nPick a difficulty", ["Easy   (3-6 letters)", "Medium (7-9 letters)", "Hard   (10+ letters)"], 1)]
                game = HangmanGame(pick_word(bank[category], difficulty, rng), category, MAX_MISTAKES)

            play_round(game, rng, clear_screen)
            stats.record(game.won, game.score())
            hangman_stats.save(stats, args.stats_file)
            show_result(game, stats)

            if args.word or not ask(style("\nPlay again? (y/n) › ", "cyan")).lower().startswith("y"):
                break
            clear(clear_screen)
    except Quit:
        pass
    print(style("\nThanks for playing Hangman! 👋", "blue"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
