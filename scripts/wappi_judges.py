import asyncio
import json
import re
from typing import Any

import httpx

from app.config import settings

CRITERIA = ("correct", "complete", "actionable", "tone", "speakable")
# Three model families, so one family's habits do not decide the score.
JUDGES = (
    "byok/astral-x/claude-haiku-5-5",
    "byok/astral-x/qwen3.8-27b",
    "byok/astral-x/agentx_llm_pro",
)
RUBRIC = """Bạn chấm câu trả lời của một trợ lý điện năng cho hộ gia đình ở Việt Nam. Bạn thấy
ngày hôm nay, câu hỏi, câu trả lời và dữ liệu mà trợ lý đã đọc từ hệ thống (không biết ai trả
lời). Dữ liệu mới hơn kiến thức của bạn: nếu dữ liệu nói khác điều bạn nhớ thì tin dữ liệu. Chấm
mỗi tiêu chí từ 1 (rất kém) đến 5 (rất tốt):
- correct: mọi con số và khẳng định trong câu trả lời đều có trong dữ liệu (làm tròn được); điều
  không có trong dữ liệu là bịa. Không có dữ liệu mà nêu số liệu cụ thể của nhà là bịa. Từ chối
  hợp lý hoặc nói không có tài liệu khi dữ liệu trống là đúng; nói "không có" trong khi dữ liệu
  có câu trả lời là sai.
- complete: trả lời đúng điều được hỏi, đủ ý chính, không lan man.
- actionable: có việc cụ thể người dùng làm tiếp được (khi câu hỏi cần), liên quan đến điều vừa
  nói, không khuyên chung chung.
- tone: tự nhiên, lịch sự, như người thật nói chuyện, không máy móc.
- speakable: đọc to nghe xuôi: câu ngắn, mỗi câu một ý, không ký hiệu, ngoặc, danh sách.
Chỉ trả về một đối tượng JSON dạng
{"correct":5,"complete":4,"actionable":3,"tone":5,"speakable":4}, không chữ nào khác."""
PASS_CORRECT = 4
PASS_MEAN = 3.5


def prompt(question: str, answer: str, evidence: str = "", today: str = "") -> str:
    read = evidence or "(trợ lý không đọc dữ liệu nào)"
    return (
        f"Hôm nay: {today}\n\nCâu hỏi của người dùng:\n{question}\n\n"
        f"Dữ liệu trợ lý đã đọc:\n{read}\n\nCâu trả lời:\n{answer}"
    )


def parse(content: str) -> dict[str, int] | None:
    found = re.search(r"\{[^{}]*\}", content or "")
    if not found:
        return None
    try:
        data = json.loads(found[0])
    except json.JSONDecodeError:
        return None
    if not all(isinstance(data.get(c), int) and 1 <= data[c] <= 5 for c in CRITERIA):
        return None
    return {c: data[c] for c in CRITERIA}


async def judge(client: httpx.AsyncClient, model: str, user: str):
    """One judge's scores, or None when it fails or answers in a shape that is not the rubric."""
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": user},
        ],
    }
    try:
        r = await client.post("/chat/completions", json=body)
        r.raise_for_status()
        return parse(r.json()["choices"][0]["message"]["content"])
    except httpx.HTTPError, KeyError, IndexError, TypeError, ValueError:
        return None


def combine(votes: list[dict[str, int] | None]) -> dict[str, Any]:
    ok = [v for v in votes if v]
    if not ok:
        return {"mean": {}, "verdict": "unjudged", "judges": 0, "agree": True}
    mean = {c: round(sum(v[c] for v in ok) / len(ok), 2) for c in CRITERIA}
    passes = [
        v["correct"] >= PASS_CORRECT and sum(v.values()) / len(CRITERIA) >= PASS_MEAN for v in ok
    ]
    return {
        "mean": mean,
        "verdict": "pass" if sum(passes) * 2 > len(ok) else "fail",
        "judges": len(ok),
        "agree": len(set(passes)) == 1,
    }


async def judge_all(question: str, answer: str, evidence: str, today: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {settings.astralx_api_key}"}
    async with httpx.AsyncClient(
        base_url=settings.astralx_base_url, headers=headers, timeout=60
    ) as client:
        user = prompt(question, answer, evidence, today)
        votes = await asyncio.gather(*(judge(client, m, user) for m in JUDGES))
    return combine(list(votes))
