"""Is every number in a text backed by the tool results? (guard_output, the summarizer).

Vietnamese and English number styles both occur ("137.386 đ", "137,386", "17,25 kWh"), so each
token is read every plausible way and matches when any reading is close to an allowed value.
"""

import re

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SMALL = 10  # ponytail: counts and ordinals up to 10 pass without a source ("2 thiết bị")


def readings(token: str) -> set[float]:
    out = set()
    for candidate in (token.replace(",", "."), token.replace(",", ""),
                      token.replace(".", "").replace(",", "."), re.sub(r"[.,]", "", token)):
        try:
            out.add(float(candidate))
        except ValueError:
            continue
    return out


def numbers(text: str) -> list[str]:
    return _NUMBER.findall(text or "")


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.011 or (b != 0 and abs(a - b) / abs(b) <= 0.01)


def ungrounded(text: str, sources: list[str]) -> list[str]:
    """The number tokens of `text` that no source text supports."""
    allowed = {v for s in sources for t in numbers(s) for v in readings(t)}
    bad = []
    for token in numbers(text):
        values = readings(token)
        if any(v <= SMALL and v == int(v) for v in values):
            continue
        if not any(_close(v, a) for v in values for a in allowed):
            bad.append(token)
    return bad
