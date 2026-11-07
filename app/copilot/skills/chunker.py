"""Skills and tools → short texts to embed (spec section 4). Pure: no database, no model."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_CHARS = 400
MIN_CHARS = 40
_SENTENCE_END = re.compile(r"(?<=[.?!;])\s+|\n+")


@dataclass(frozen=True)
class ChunkIn:
    kind: str  # description | example | tool | param
    ord: int
    text: str


def no_tone(text: str) -> str:
    """Lower case without Vietnamese tone marks: "Bếp tuần qua" → "bep tuan qua"."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def _cut(text: str) -> list[str]:
    """Whole words, at most MAX_CHARS each."""
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > MAX_CHARS:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*out, line] if line else out


def sentences(text: str) -> list[str]:
    """Split at sentence ends, merge pieces under MIN_CHARS into the next, cut long ones."""
    merged: list[str] = []
    carry = ""
    for piece in (p.strip() for p in _SENTENCE_END.split(text)):
        if not piece:
            continue
        carry = f"{carry} {piece}".strip()
        if len(carry) >= MIN_CHARS:
            merged.append(carry)
            carry = ""
    if carry:
        if merged and len(merged[-1]) + 1 + len(carry) <= MAX_CHARS:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return [cut for s in merged for cut in _cut(s)]


def example_chunks(examples: list[str], start: int = 0) -> list[ChunkIn]:
    """Each example as written and without tone marks; duplicates dropped."""
    out: list[ChunkIn] = []
    seen: set[str] = set()
    for example in examples:
        for text in (example.strip(), no_tone(example.strip())):
            if text and text not in seen:
                seen.add(text)
                out.append(ChunkIn("example", start + len(out), text[:MAX_CHARS]))
    return out


def skill_chunks(name: str, description: str, examples: list[str]) -> list[ChunkIn]:
    """Description sentences, then the examples (instructions are not embedded)."""
    out = [ChunkIn("description", i, t) for i, t in enumerate(sentences(f"{name}. {description}"))]
    return out + example_chunks(examples, start=len(out))


def tool_chunks(name: str, label: str, description: str, parameters: dict[str, Any]
                ) -> list[ChunkIn]:
    out = [ChunkIn("tool", i, t) for i, t in enumerate(_cut(f"{label} ({name}): {description}"))]
    for arg, spec in (parameters.get("properties") or {}).items():
        if spec.get("description"):
            text = f"{name}.{arg}: {spec['description']}"[:MAX_CHARS]
            out.append(ChunkIn("param", len(out), text))
    return out


def content_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()
