"""The chat model on OpenRouter and the structured calls. The prompts and the model
settings are in app/copilot/config (prompts.yaml, llm_config.yaml).

The model chooses and explains; it never sees a database and never writes SQL.
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from ..config.settings import LLM, PROMPTS, settings


class CopilotDisabledError(RuntimeError):
    """No OpenRouter key or model, or no Copilot database login: the router answers 503."""


def chat_model():
    if not settings.llm_enabled:
        raise CopilotDisabledError("set OPENROUTER_API_KEY and OPENROUTER_MODEL")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        temperature=LLM["temperature"],
        timeout=LLM["timeout_s"],
        max_retries=LLM["max_retries"],
        extra_body=None if LLM.get("reasoning", True) else {"reasoning": {"enabled": False}},
    )


async def structured[T: BaseModel](model, schema: type[T], system: str, payload: dict) -> T:
    """One structured call (tool calling: the most widely supported mode on OpenRouter).

    Models sometimes answer without calling the tool: one retry, then the error propagates.
    """
    runnable = model.with_structured_output(schema, method="function_calling")
    messages = [SystemMessage(system),
                HumanMessage(json.dumps(payload, ensure_ascii=False, default=str))]
    for attempt in (1, 2):
        out = await runnable.ainvoke(messages)
        try:
            return out if isinstance(out, schema) else schema.model_validate(out)
        except ValidationError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


async def text(model, system: str, payload: dict) -> str:
    out = await model.ainvoke(
        [SystemMessage(system), HumanMessage(json.dumps(payload, ensure_ascii=False, default=str))]
    )
    return out.content if isinstance(out.content, str) else str(out.content)


# KeyError at import when prompts.yaml lacks one: fail at start, not on the first question
AGENT = PROMPTS["agent"]
SKILL_CHOICE = PROMPTS["skill_choice"]
REWRITE = PROMPTS["rewrite"]
ANSWER = PROMPTS["answer"]
PHRASE = PROMPTS["phrase"]
SUMMARIZE = PROMPTS["summarize"]
