import re

MAX_WORDS = 25
MAX_NUMBERS = 4
SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def speak_lint(text: str) -> list[str]:
    """What makes an answer rough to hear: long sentences, asides, crowded figures, markup."""
    found: set[str] = set()
    for sentence in filter(None, (s.strip() for s in SENTENCE.split(text))):
        if len(sentence.split()) > MAX_WORDS:
            found.add("long_sentence")
        if len(NUMBER.findall(sentence)) > MAX_NUMBERS:
            found.add("many_numbers")
    if re.search(r"[()]", text):
        found.add("parentheses")
    if re.search(r"\s[—–-]\s", text):
        found.add("dash_aside")
    if re.search(r"[*_#`]|^\s*(?:[-•]|\d+\.)\s", text, re.MULTILINE):
        found.add("markup")
    return sorted(found)
