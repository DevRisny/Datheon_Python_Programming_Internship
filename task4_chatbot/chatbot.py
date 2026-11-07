#!/usr/bin/env python3
"""
Dex: a rule-based terminal assistant for Datheon interns.

It understands questions about tasks, submission, certificates, deadlines, fees, LinkedIn,
pausing, logging in and contacting the team. It can answer several questions in one message,
remembers your name, says if the support team is online right now, and suggests topics when
it is unsure. Type 'bye', 'exit' or 'quit' to leave.

    python chatbot.py
    python chatbot.py --ask "How do I submit and is it free?"   # one question, then exit
    python chatbot.py --transcript chat.txt                      # also save the conversation

Datheon Python Programming Internship · Task 4 · J. Risny Suha
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import term
from chatbot_core import Chatbot, KnowledgeBase, Reply
from term import style

HERE = Path(__file__).resolve().parent


def render(text: str) -> str:
    """**bold** and `code` from the answers become terminal styles."""
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: style(m.group(1), "bold"), text)
    return re.sub(r"`(.+?)`", lambda m: style(m.group(1), "cyan"), text)


def wrap(text: str, size: int) -> list[str]:
    """Word-wraps styled text by its visible width, so colours never break a line in the wrong place."""
    lines, current, length = [], [], 0
    for word in text.split(" "):
        visible = len(term.strip(word))
        if current and length + 1 + visible > size:
            lines.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += visible + (1 if length else 0)
    lines.append(" ".join(current))
    return lines


def plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|`(.+?)`", lambda m: m.group(1) or m.group(2), text)


class Transcript:
    def __init__(self, path: Path | None):
        self.path = path
        self.lines: list[str] = []

    def add(self, who: str, text: str) -> None:
        self.lines.append(f"[{datetime.now():%H:%M:%S}] {who}: {plain(text)}")

    def save(self) -> None:
        if self.path:
            self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def show(bot: Chatbot, reply: Reply, delay: float, transcript: Transcript) -> None:
    color = {"fallback": "yellow", "unsure": "yellow", "goodbye": "magenta", "help": "teal"}.get(reply.kind, "blue")
    prefix = style(f"  {bot.kb.bot_name} › ", color, "bold")
    indent = " " * (len(bot.kb.bot_name) + 5)
    if delay and sys.stdout.isatty():
        print(style(f"  {bot.kb.bot_name} is typing…", "grey"), end="\r", flush=True)
        time.sleep(min(1.2, delay * (1 + sum(len(l) for l in reply.lines) / 160)))
        print(" " * 30, end="\r")
    room = term.width() - len(indent) - 1
    first = True
    for line in reply.lines:
        for part in wrap(render(line), room):
            print((prefix if first else indent) + part)
            first = False
        transcript.add(bot.kb.bot_name, line)
    if reply.kind == "answer" and reply.confidence:
        print(indent + style(f"matched: {', '.join(reply.intents)} · confidence {reply.confidence:.0%}", "grey"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rule-based Datheon student support chatbot.")
    parser.add_argument("--ask", help="answer one message and exit")
    parser.add_argument("--transcript", type=Path, help="save the conversation to this text file")
    parser.add_argument("--fast", action="store_true", help="no typing pause before answers")
    parser.add_argument("--seed", type=int, help="fixed random seed, so replies repeat exactly (for testing)")
    parser.add_argument("--no-color", action="store_true", help="plain text output")
    args = parser.parse_args(argv)
    if args.no_color:
        term.set_color(False)

    try:
        kb = KnowledgeBase.load(HERE / "data" / "intents.json", HERE / "data" / "sample_faq.json")
    except (OSError, ValueError, KeyError) as error:
        print(style(f"Could not load the knowledge base: {error}", "red"))
        return 1
    bot = Chatbot(kb, random.Random(args.seed))
    transcript = Transcript(args.transcript)
    delay = 0 if args.fast or args.ask else 0.45

    if args.ask:
        show(bot, bot.reply(args.ask), 0, transcript)
        return 0

    is_open, when = bot.open_now()
    print(term.box([style(f"{kb.bot_name} · Datheon Student Support Assistant", "bold"),
                    "Ask about tasks, submission, certificates, deadlines, fees and more.",
                    style(f"Support team: {'online' if is_open else 'offline'} · {when}", "green" if is_open else "grey"),
                    style("Type help for topics · more for details · bye to leave", "grey")], color="blue"))
    print()
    show(bot, Reply([bot._say("greeting")], kind="small_talk"), 0, transcript)
    try:
        while True:
            try:
                text = input(style("\n  You › ", "green", "bold"))
            except (EOFError, KeyboardInterrupt):
                print()
                show(bot, bot.goodbye(), 0, transcript)
                break
            transcript.add("You", text)
            reply = bot.reply(text)
            show(bot, reply, delay, transcript)
            if reply.ended:
                break
    finally:
        transcript.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
