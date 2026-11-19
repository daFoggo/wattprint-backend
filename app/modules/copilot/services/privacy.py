import re

# Personal data a question does not need, found by pattern (and by the word before it where the
# digits alone could be anything), replaced before it is stored or sent to the model.
# shortcut: patterns only, no names or addresses (no Vietnamese NER model here); add one if users
# paste those often.
LABELS = {
    "vi": {
        "email": "[email]",
        "card": "[số thẻ]",
        "id": "[số giấy tờ]",
        "phone": "[số điện thoại]",
        "account": "[số tài khoản]",
    },
    "en": {
        "email": "[email]",
        "card": "[card number]",
        "id": "[ID number]",
        "phone": "[phone number]",
        "account": "[account number]",
    },
}
_SEP = r"[ .-]?"
PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("card", re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")),  # kept only if Luhn holds
    ("id", re.compile(r"(?<!\d)0\d{11}(?!\d)")),  # CCCD: 12 digits from a province code
    (
        "phone",
        re.compile(
            rf"(?<![\d+])(?:\+?84{_SEP}|0)(?:[35789](?:{_SEP}\d){{8}}|2(?:{_SEP}\d){{9}})(?!\d)"
        ),
    ),
    # Digits that are personal only after a word naming them (old ID card, passport, account).
    (
        "id",
        re.compile(
            r"(?i)(?:cmnd|cccd|căn cước|chứng minh(?: nhân dân| thư)?|hộ chiếu|passport|"
            r"id number)\W{0,12}([a-z]?\d{8,12})(?!\d)"
        ),
    ),
    (
        "account",
        re.compile(
            r"(?i)(?:stk|số tài khoản|tài khoản(?: ngân hàng)?|account(?: number)?)\W{0,12}"
            r"(\d(?:[ .-]?\d){5,18})(?!\d)"
        ),
    ),
]


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(map(int, reversed(digits))):
        total += d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2)
    return total % 10 == 0


def redact(text: str, lang: str) -> tuple[str, list[str]]:
    """The text with personal data replaced by a label, and the kinds found."""
    labels, found = LABELS[lang], []
    for kind, pattern in PATTERNS:

        def swap(m: re.Match[str], kind: str = kind) -> str:
            value = m[1] if m.re.groups else m[0]
            if kind == "card" and not _luhn(re.sub(r"\D", "", value)):
                return m[0]
            found.append(kind)
            return m[0].replace(value, labels[kind])

        text = pattern.sub(swap, text)
    return text, sorted(set(found))
