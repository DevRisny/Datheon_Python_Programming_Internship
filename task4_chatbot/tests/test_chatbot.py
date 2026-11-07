import random
from datetime import datetime
from pathlib import Path

import pytest

import chatbot as app
from chatbot_core import IST, Chatbot, KnowledgeBase, State, normalise, split_questions, stem

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def kb():
    return KnowledgeBase.load(DATA / "intents.json", DATA / "sample_faq.json")


def make_bot(kb, when=datetime(2026, 11, 9, 11, 0, tzinfo=IST)):   # a Monday, 11 AM
    return Chatbot(kb, random.Random(0), now=lambda: when)


def tags(bot, text):
    return bot.reply(text).intents


def test_normalise_expands_contractions_and_punctuation():
    assert normalise("What's the DEADLINE??") == "what is the deadline"
    assert normalise("I'm  done!") == "i am done"
    assert stem("certificates") == stem("certificate") and stem("submitting") == stem("submit")


@pytest.mark.parametrize("question,tag", [
    ("What are your hours of operation?", "hours"),
    ("when are you open on saturday", "hours"),
    ("How do I submit my internship project?", "submit"),
    ("where do I paste my github link", "submit"),
    ("When will I receive my certificate?", "certificate"),
    ("how many tasks do I need to complete", "tasks"),
    ("what is the deadline", "duration"),
    ("is there any fee to pay", "fees"),
    ("should I post on linkedin", "linkedin"),
    ("can I pause during my exams", "pause"),
    ("I lost my application id", "application_id"),
    ("how can I contact a mentor", "contact"),
    ("how do I create a public repo on github", "github_help"),
])
def test_intents(kb, question, tag):
    assert tag in tags(make_bot(kb), question)


def test_official_faq_answer_is_used(kb):
    reply = make_bot(kb).reply("When will I receive my certificate?")
    assert reply.lines[0].startswith("Certificates are reviewed and issued within 3-5 business days")
    assert "QR code" in reply.lines[0]


def test_two_questions_in_one_message(kb):
    reply = make_bot(kb).reply("How do I submit my project and is it free?")
    assert reply.intents == ["submit", "fees"]
    assert any(line.startswith("▸") for line in reply.lines)


def test_split_questions():
    assert split_questions("When are you open? And how do I submit") == ["When are you open", "how do I submit"]


def test_hours_say_if_the_team_is_online(kb):
    monday = make_bot(kb).reply("what are your opening hours")
    assert "online" in " ".join(monday.lines)
    sunday = make_bot(kb, datetime(2026, 11, 8, 11, 0, tzinfo=IST)).reply("what are your opening hours")
    assert "offline" in " ".join(sunday.lines)


def test_greeting_and_name_memory(kb):
    bot = make_bot(kb)
    assert bot.reply("hello").kind == "small_talk"
    assert bot.state is State.LISTENING
    assert "Risny" in bot.reply("my name is risny").lines[0]
    assert bot.user_name == "Risny"
    assert "Risny" in bot.reply("thanks").lines[0]


def test_feelings_are_not_mistaken_for_names(kb):
    bot = make_bot(kb)
    bot.reply("I'm confused about the deadline")
    assert bot.user_name == ""


def test_follow_up_more(kb):
    bot = make_bot(kb)
    bot.reply("how do I submit")
    reply = bot.reply("tell me more")
    assert reply.kind == "follow_up" and "24 hours" in reply.lines[0]


def test_unknown_question_falls_back_with_help(kb):
    bot = make_bot(kb)
    first = bot.reply("what is the weather like on mars")
    assert first.kind in {"fallback", "unsure"}
    second = bot.reply("tell me a recipe for biryani")
    assert any("hello@datheon.in" in line for line in second.lines)   # offers a human after two misses


def test_typo_gets_a_suggestion(kb):
    reply = make_bot(kb).reply("certficate")
    assert "Certificates" in " ".join(reply.lines)


def test_identity_help_and_time(kb):
    bot = make_bot(kb)
    assert "rule-based" in bot.reply("who are you?").lines[0]
    assert bot.reply("help").kind == "help"
    assert "Monday" in bot.reply("what time is it").lines[0]


@pytest.mark.parametrize("word", ["bye", "exit", "quit", "Goodbye!", "ok bye"])
def test_exit_commands(kb, word):
    bot = make_bot(kb)
    reply = bot.reply(word)
    assert reply.ended and bot.state is State.ENDED
    assert bot.reply("hello").ended


def test_goodbye_lists_topics(kb):
    bot = make_bot(kb)
    bot.reply("how do I submit")
    assert "Submitting your project" in " ".join(bot.reply("bye").lines)


def test_empty_message(kb):
    assert make_bot(kb).reply("   ").kind == "help"


def test_one_shot_cli(capsys):
    assert app.main(["--ask", "is it free?", "--no-color"]) == 0
    assert "no enrollment fee" in capsys.readouterr().out


def test_conversation_cli_with_transcript(tmp_path, monkeypatch, capsys):
    answers = iter(["hi", "my name is Risny", "how do I submit and when do I get my certificate", "more", "bye"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    log = tmp_path / "chat.txt"
    assert app.main(["--fast", "--no-color", "--seed", "1", "--transcript", str(log)]) == 0
    out = capsys.readouterr().out
    assert "Nice to meet you, Risny" in out
    assert "Bye, Risny" in out or "Goodbye, Risny" in out
    saved = log.read_text(encoding="utf-8")
    assert "You: how do I submit" in saved and "**" not in saved


def test_wrap_keeps_words_whole():
    lines = app.wrap("one two three four five six", 9)
    assert lines == ["one two", "three", "four five", "six"]
