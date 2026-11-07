"""Small helpers shared by the Copilot."""

import json
import re
from typing import Any

_VI_MARKS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]")


_VI_WORDS = {"may", "giat", "hom", "qua", "nay", "dien", "bao", "nhieu", "ngay", "tuan", "thang",
             "dung", "nha", "toi", "cua", "lanh", "noi", "binh", "quat", "am", "nuoc", "khong"}


def as_json(value: Any) -> Any:
    """asyncpg returns jsonb as text."""
    return json.loads(value) if isinstance(value, str) else value


def detect_lang(question: str) -> str:
    lower = question.lower()
    if _VI_MARKS.search(lower) or len(set(re.findall(r"[a-z]+", lower)) & _VI_WORDS) >= 2:
        return "vi"
    return "en"
