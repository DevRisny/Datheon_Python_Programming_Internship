"""The rule-based brain of the assistant: no printing, no input(), so it is fully unit tested.

How a message is understood
  1. normalise   lower-case, expand contractions ("what's" -> "what is"), remove punctuation
  2. small talk   greetings, thanks, "who are you", "my name is ...", help, time, goodbye
  3. split        "When are you open and how do I submit?" -> two questions
  4. score        every intent: regex patterns (+3), keywords (+1 each), similarity to example questions
  5. answer       the best intents above the confidence threshold, in the order they were asked
  6. fall back    if nothing is confident: say so, suggest the closest topics, offer a human contact
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher, get_close_matches
from enum import Enum
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # very old Python or no tz database (some Windows installs)
    IST = timezone(timedelta(hours=5, minutes=30), "IST")

CONTRACTIONS = {
    "what's": "what is", "whats": "what is", "where's": "where is", "how's": "how is", "when's": "when is",
    "who's": "who is", "it's": "it is", "i'm": "i am", "im": "i am", "can't": "can not", "cannot": "can not",
    "don't": "do not", "dont": "do not", "doesn't": "does not", "didn't": "did not", "won't": "will not",
    "i've": "i have", "i'll": "i will", "you're": "you are", "u": "you", "r": "are", "pls": "please",
    "plz": "please", "thx": "thanks", "ty": "thank you", "cert": "certificate", "certs": "certificates",
}
STOPWORDS = set("a an the is are am was were be to of in on for and or i me my you your it this that do does "
                "did can could would should will what when where how which who please with at by from about "
                "there have has get got any".split())
EXIT_WORDS = {"bye", "goodbye", "exit", "quit", "q", "see you", "see ya", "good night", "goodnight", "bye bye", "cya"}
HELP_WORDS = {"help", "menu", "topics", "options", "what can you do", "what can you help with", "commands"}
MORE_WORDS = {"more", "tell me more", "more details", "more info", "explain", "explain more", "and", "and?",
              "what else", "go on", "details", "elaborate", "anything else to know"}
CONFIDENT = 2.5   # score needed to answer
UNSURE = 1.0      # below this the message is not understood at all
NAME_STOP = {"fine", "good", "ok", "okay", "confused", "lost", "stuck", "here", "back", "done", "not", "new",
             "a", "an", "the", "sorry", "trying", "looking", "student", "intern", "interested", "ready", "great"}


def normalise(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    words = [CONTRACTIONS.get(w, w) for w in re.findall(r"[a-z0-9@.'+-]+", text)]
    text = " ".join(words).replace("'", "")
    return re.sub(r"\s+", " ", re.sub(r"(?<!\w)[.-]|[.-](?!\w)", " ", text)).strip()


def stem(word: str) -> str:
    """A tiny stemmer so 'certificates' matches 'certificate' and 'submitting' matches 'submit'."""
    for suffix in ("ations", "ation", "ing", "ies", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    else:
        if word.endswith(("sses", "xes", "ches", "shes", "zes")):
            word = word[:-2]
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
        word = word[:-1]   # submitt -> submit
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in normalise(text).split() if w not in STOPWORDS]


@dataclass
class Intent:
    tag: str
    title: str
    patterns: list[re.Pattern]
    keywords: set[str]
    phrases: list[str]               # multi-word keywords, matched as text
    responses: list[str]
    more: str = ""
    examples: list[str] = field(default_factory=list)
    with_faq: str = ""               # extra detail added after an official FAQ answer

    def score(self, text: str) -> float:
        norm = normalise(text)
        toks = set(tokens(text))
        score = 3.0 * min(2, sum(1 for p in self.patterns if p.search(norm)))
        score += len(toks & self.keywords)
        score += 1.5 * sum(1 for ph in self.phrases if ph in norm)
        if self.examples:
            best = max(SequenceMatcher(None, norm, normalise(e)).ratio() for e in self.examples)
            if best >= 0.55:
                score += 4.0 * best
        return score


@dataclass
class Reply:
    lines: list[str]
    intents: list[str] = field(default_factory=list)
    kind: str = "answer"         # answer | small_talk | fallback | help | goodbye | follow_up | unsure
    confidence: float = 0.0
    ended: bool = False


class State(Enum):
    GREETING = "greeting"        # waiting for the first message
    LISTENING = "listening"      # identifying what the user needs
    ENDED = "ended"


class KnowledgeBase:
    def __init__(self, intents: list[Intent], small_talk: dict[str, list[str]], greetings: set[str],
                 bot_name: str = "Dex"):
        self.intents = intents
        self.small_talk = small_talk
        self.greetings = greetings
        self.bot_name = bot_name

    @classmethod
    def load(cls, intents_file: Path, faq_file: Path | None = None) -> "KnowledgeBase":
        data = json.loads(intents_file.read_text(encoding="utf-8"))
        intents = []
        for item in data["intents"]:
            keywords = [k.lower() for k in item.get("keywords", [])]
            intents.append(Intent(
                tag=item["tag"], title=item.get("title", item["tag"]),
                patterns=[re.compile(p) for p in item.get("patterns", [])],
                keywords={stem(k) for k in keywords if " " not in k},
                phrases=[k for k in keywords if " " in k],
                responses=item["responses"], more=item.get("more", ""),
                examples=item.get("examples", []), with_faq=item.get("with_faq", "")))
        greetings = {"hello", "hi", "hey", "hiya", "good morning", "good afternoon", "good evening", "greetings"}
        if faq_file and faq_file.exists():
            faq = json.loads(faq_file.read_text(encoding="utf-8"))
            greetings |= {g.lower() for g in faq.get("greetings", [])}
            for entry in faq.get("faqs", []):
                question, answer = entry["question"], entry["answer"]
                best = max(intents, key=lambda i: i.score(question), default=None)
                if best and best.score(question) >= CONFIDENT:
                    best.examples.append(question)              # helps fuzzy matching
                    extra = best.with_faq
                    best.responses = [f"{answer} {extra}".strip()]  # the official FAQ answer comes first
                else:                                           # a brand-new FAQ becomes its own intent
                    tag = "faq_" + "_".join(tokens(question)[:3])
                    intents.append(Intent(tag, question, [], set(tokens(question)), [], [answer], "", [question]))
        bot = data.get("bot", {})
        return cls(intents, data.get("small_talk", {}), greetings, bot.get("name", "Dex"))


def split_questions(text: str) -> list[str]:
    """'When are you open? And how do I submit' -> ['When are you open', 'how do I submit']."""
    parts = re.split(r"[?!;]+|\.(?:\s|$)|\b(?:and also|also|and|plus|then)\b", text, flags=re.I)
    return [p.strip(" ,.") for p in parts if len(p.strip(" ,.").split()) >= 1]


class Chatbot:
    def __init__(self, kb: KnowledgeBase, rng: random.Random | None = None, now=None):
        self.kb = kb
        self.rng = rng or random.Random()
        self.now = now or (lambda: datetime.now(IST))
        self.state = State.GREETING
        self.user_name = ""
        self.last_intent: Intent | None = None
        self.topics: list[str] = []
        self.misses = 0
        self.turns = 0

    # ----- helpers -----
    def _say(self, key: str, **extra: str) -> str:
        options = self.kb.small_talk.get(key) or [""]
        name = f", {self.user_name}" if self.user_name else ""
        return self.rng.choice(options).format(name=name, **extra)

    def open_now(self) -> tuple[bool, str]:
        now = self.now().astimezone(IST)
        is_open = now.weekday() < 5 and 9 <= now.hour < 18
        return is_open, now.strftime("%A, %I:%M %p IST").replace(" 0", " ")

    def _intent_answer(self, intent: Intent) -> list[str]:
        lines = [self.rng.choice(intent.responses)]
        if intent.tag == "hours":
            is_open, when = self.open_now()
            lines.append(f"Right now it is {when}, so the team is " +
                         ("**online** ✅." if is_open else "**offline**. They will reply on the next working day."))
        return lines

    def _detect_name(self, raw: str) -> str | None:
        m = re.search(r"\b(?:my name is|call me|this is)\s+([A-Za-z][A-Za-z'-]{1,20})", raw, re.I)
        if not m:
            m = re.search(r"\b(?:i am|i'm|im)\s+([A-Z][A-Za-z'-]{1,20})\b", raw)
        if m and m.group(1).lower() not in NAME_STOP:
            return m.group(1).capitalize()
        return None

    def _small_talk(self, raw: str, norm: str) -> Reply | None:
        name = self._detect_name(raw)
        if name:
            self.user_name = name
            return Reply([self._say("name_saved", raw_name=name)], kind="small_talk")
        if norm in EXIT_WORDS or re.fullmatch(r"(ok |okay |thanks |thank you )?(bye|goodbye|good night)( .*)?", norm):
            return self.goodbye()
        if norm in HELP_WORDS or re.fullmatch(r"(show )?(the )?(help|menu|topics)( please)?", norm):
            return self.help()
        if norm in MORE_WORDS and self.last_intent:
            more = self.last_intent.more or "That's everything I know about it. Ask me another question!"
            return Reply([more], [self.last_intent.tag], kind="follow_up")
        words = norm.split()
        if words and (norm in self.kb.greetings or (len(words) <= 4 and (words[0] in self.kb.greetings or
                                                                        " ".join(words[:2]) in self.kb.greetings))):
            rest = " ".join(w for w in words if w not in {"hi", "hello", "hey", "there", "dex", "good", "morning",
                                                          "afternoon", "evening"})
            if not rest:
                return Reply([self._say("greeting")], kind="small_talk")
        if re.search(r"\bhow are (you|things)\b|\bhow is it going\b", norm):
            return Reply([self._say("how_are_you")], kind="small_talk")
        if re.fullmatch(r"(ok |okay |great |cool )?(thanks|thank you|thank you so much|thanks a lot|cheers)( dex)?( .*)?", norm) \
                and len(words) <= 6:
            return Reply([self._say("thanks")], kind="small_talk")
        if re.search(r"\b(who|what) are you\b|\bare you (a )?(bot|robot|human|real|ai)\b|\byour name\b", norm):
            return Reply([self._say("identity")], kind="small_talk")
        if re.search(r"\bwhat (time|day|date) is it\b|\btodays date\b|\bwhat is the (time|date)\b", norm):
            _, when = self.open_now()
            return Reply([f"It is {when}."], kind="small_talk")
        return None

    def help(self) -> Reply:
        topics = ", ".join(f"**{i.title}**" for i in self.kb.intents if not i.tag.startswith("faq_"))
        return Reply([f"I can answer questions about: {topics}.",
                      "Try: \"How do I submit?\" or \"When will I get my certificate and is it free?\"",
                      "Type **more** after an answer for extra details, or **bye** to leave."], kind="help")

    def goodbye(self) -> Reply:
        self.state = State.ENDED
        lines = [self._say("goodbye")]
        if self.topics:
            lines.append(f"We covered: {', '.join(dict.fromkeys(self.topics))}.")
        return Reply(lines, kind="goodbye", ended=True)

    def rank(self, text: str) -> list[tuple[float, Intent]]:
        return sorted(((i.score(text), i) for i in self.kb.intents), key=lambda x: x[0], reverse=True)

    # ----- main entry -----
    def reply(self, raw: str) -> Reply:
        if self.state is State.ENDED:
            return Reply(["This chat has ended. Start me again to ask more questions."], kind="goodbye", ended=True)
        self.turns += 1
        norm = normalise(raw)
        if not norm:
            return Reply(["I'm listening. Type a question, **help** for topics, or **bye** to leave."], kind="help")

        small = self._small_talk(raw, norm)
        if small:
            if self.state is State.GREETING and small.kind != "goodbye":
                self.state = State.LISTENING
            return small
        self.state = State.LISTENING

        found: list[tuple[float, Intent]] = []
        for part in split_questions(raw) or [raw]:
            score, intent = self.rank(part)[0]
            if score >= CONFIDENT and intent not in [i for _, i in found]:
                found.append((score, intent))
        if not found:
            score, intent = self.rank(raw)[0]
            if score >= CONFIDENT:
                found.append((score, intent))

        if found:
            self.misses = 0
            lines: list[str] = []
            for _, intent in found[:3]:
                if len(found) > 1:
                    lines.append(f"▸ {intent.title}")
                lines += self._intent_answer(intent)
                self.topics.append(intent.title)
            self.last_intent = found[-1][1]
            confidence = min(1.0, min(s for s, _ in found) / 6)
            if self.user_name and self.rng.random() < 0.25:
                lines.append(f"Anything else, {self.user_name}?")
            return Reply(lines, [i.tag for _, i in found], kind="answer", confidence=confidence)

        return self._fallback(raw)

    def _fallback(self, raw: str) -> Reply:
        self.misses += 1
        ranked = [(s, i) for s, i in self.rank(raw) if s >= UNSURE][:2]
        lines = [self._say("fallback")]
        if ranked:
            lines.append("Did you mean: " + " or ".join(f"**{i.title}**" for _, i in ranked) + "?")
            kind = "unsure"
        else:
            words = [w for w in tokens(raw)]
            vocabulary = sorted({k for i in self.kb.intents for k in i.keywords})
            close = [m for w in words for m in get_close_matches(w, vocabulary, n=1, cutoff=0.75)]
            hit = [i for i in self.kb.intents if set(close) & i.keywords]
            if hit:
                lines.append(f"Did you mean **{hit[0].title}**? (I spotted a possible typo.)")
            else:
                lines.append("Try asking about tasks, submission, certificates, deadlines or fees, or type **help**.")
            kind = "fallback"
        if self.misses >= 2:
            lines.append("You can also email a person at **hello@datheon.in**, they are happy to help.")
        return Reply(lines, kind=kind)
