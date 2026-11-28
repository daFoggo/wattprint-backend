import time

import pytest

from app.config import settings
from app.modules.copilot.services import guard, llm
from app.modules.copilot.utils import CopilotUnavailableError


@pytest.fixture(autouse=True)
def both_keys(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "astralx_api_key", "ax-key")
    monkeypatch.setattr(settings, "copilot_llm_order", "openrouter,astralx")
    llm._down.clear()
    yield
    llm._down.clear()


def fake(behaviour: dict):
    """Replace the one-provider attempt: behaviour[name] lists deltas, or an exception to raise
    after the deltas given before it."""
    calls = []

    async def attempt(provider, messages, tools, turn):
        calls.append(provider.name)
        for step in behaviour[provider.name]:
            if isinstance(step, Exception):
                raise step
            turn.text += step
            yield step

    return attempt, calls


async def run() -> tuple[str, llm.Turn]:
    turn = llm.Turn()
    out = [d async for d in llm.stream([], None, turn)]
    return "".join(out), turn


async def test_the_first_provider_answers_and_the_second_is_not_called(monkeypatch):
    attempt, calls = fake({"openrouter": ["a", "b"], "astralx": ["x"]})
    monkeypatch.setattr(llm, "_attempt", attempt)
    assert (await run())[0] == "ab"
    assert calls == ["openrouter"]


async def test_a_provider_down_before_any_word_hands_over_to_the_other(monkeypatch):
    attempt, calls = fake({"openrouter": [CopilotUnavailableError("400")], "astralx": ["hi"]})
    monkeypatch.setattr(llm, "_attempt", attempt)
    text, turn = await run()
    assert text == "hi" and turn.text == "hi"
    assert calls == ["openrouter", "astralx"]


async def test_a_provider_that_fails_midway_is_not_retried_on_the_other(monkeypatch):
    attempt, calls = fake({"openrouter": ["par", CopilotUnavailableError("cut")], "astralx": ["x"]})
    monkeypatch.setattr(llm, "_attempt", attempt)
    with pytest.raises(CopilotUnavailableError):
        await run()
    assert calls == ["openrouter"]


async def test_a_provider_that_just_failed_is_skipped_for_a_while(monkeypatch):
    attempt, calls = fake({"openrouter": [CopilotUnavailableError("400")], "astralx": ["hi"]})
    monkeypatch.setattr(llm, "_attempt", attempt)
    await run()
    calls.clear()
    await run()
    assert calls == ["astralx"]


async def test_when_every_provider_is_down_the_last_error_is_raised(monkeypatch):
    attempt, _ = fake(
        {"openrouter": [CopilotUnavailableError("a")], "astralx": [CopilotUnavailableError("b")]}
    )
    monkeypatch.setattr(llm, "_attempt", attempt)
    with pytest.raises(CopilotUnavailableError):
        await run()
    # all cooling: the next question still tries them rather than failing without a call
    with pytest.raises(CopilotUnavailableError):
        await run()


async def test_without_any_key_the_assistant_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "astralx_api_key", "")
    with pytest.raises(CopilotUnavailableError):
        await run()


async def test_the_order_setting_puts_astralx_first(monkeypatch):
    monkeypatch.setattr(settings, "copilot_llm_order", "astralx,openrouter")
    attempt, calls = fake({"openrouter": ["a"], "astralx": ["x"]})
    monkeypatch.setattr(llm, "_attempt", attempt)
    assert (await run())[0] == "x"
    assert calls == ["astralx"]


async def test_a_handover_drops_what_the_failed_provider_left_on_the_turn(monkeypatch):
    async def attempt(provider, messages, tools, turn):
        if provider.name == "openrouter":
            turn.usage, turn.calls = {"cost": 1}, [llm.Call("c1", "tool")]
            raise CopilotUnavailableError("cut")
        turn.usage = {"total_tokens": 7}
        turn.text += "hi"
        yield "hi"

    monkeypatch.setattr(llm, "_attempt", attempt)
    _, turn = await run()
    assert turn.usage == {"total_tokens": 7, "provider": "astralx"}
    assert turn.calls == [] and turn.text == "hi"


async def test_the_cooldown_counts_from_the_moment_of_the_failure(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])

    async def attempt(provider, messages, tools, turn):
        if provider.name == "openrouter":
            clock[0] += 20  # a slow failure
            raise CopilotUnavailableError("timeout")
        yield "hi"

    monkeypatch.setattr(llm, "_attempt", attempt)
    await run()
    assert llm._down["openrouter"] == 120.0 + settings.copilot_llm_cooldown_s


async def test_provider_names_in_the_order_setting_ignore_case(monkeypatch):
    monkeypatch.setattr(settings, "copilot_llm_order", "OpenRouter, AstralX")
    assert [p.name for p in llm.providers()] == ["openrouter", "astralx"]


async def test_the_real_attempt_sends_astralx_its_body_and_reads_its_stream(monkeypatch):
    import json

    import httpx

    sent = {}
    sse = (
        "\n\n".join(
            "data: " + json.dumps(c)
            for c in (
                {"choices": [{"delta": {"content": "Chào"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "t1",
                                        "index": 0,
                                        "function": {"name": "w", "arguments": '{"a'},
                                    }
                                ],
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '":1}'}}]}}
                    ]
                },
                {"choices": [], "usage": {"total_tokens": 9}},
            )
        )
        + "\n\ndata: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        sent["auth"] = request.headers["authorization"]
        sent["body"] = json.loads(request.content)
        sent["path"] = request.url.path
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(settings, "copilot_llm_order", "astralx")
    turn = llm.Turn()
    out = [d async for d in llm.stream([{"role": "user", "content": "x"}], None, turn)]
    assert out == ["Chào"] and turn.usage == {"total_tokens": 9, "provider": "astralx"}
    assert [(c.id, c.name, c.arguments) for c in turn.calls] == [("t1", "w", '{"a":1}')]
    assert sent["auth"] == "Bearer ax-key" and sent["path"].endswith("/chat/completions")
    assert sent["body"]["model"] == settings.astralx_chat_model
    assert sent["body"]["stream_options"] == {"include_usage": True} and "usage" not in sent["body"]


HARD = llm.ProviderError("503", hard=True)


def failing(name_to_error: dict):
    async def attempt(provider, messages, tools, turn):
        if provider.name in name_to_error:
            raise name_to_error[provider.name]
        turn.text += "ok"
        yield "ok"

    return attempt


async def test_a_hard_failure_rests_the_provider_at_once(monkeypatch):
    monkeypatch.setattr(llm, "_attempt", failing({"openrouter": HARD}))
    await run()
    assert llm.resting("openrouter")


async def test_a_soft_failure_rests_the_provider_only_if_the_other_one_answers(monkeypatch):
    soft = llm.ProviderError("400", hard=False)
    monkeypatch.setattr(llm, "_attempt", failing({"openrouter": soft}))
    await run()  # astralx answered the same request: it is openrouter that is broken
    assert llm.resting("openrouter")


async def test_a_request_both_providers_refuse_rests_neither(monkeypatch):
    soft = llm.ProviderError("400", hard=False)
    monkeypatch.setattr(llm, "_attempt", failing({"openrouter": soft, "astralx": soft}))
    with pytest.raises(CopilotUnavailableError):
        await run()
    assert not llm.resting("openrouter") and not llm.resting("astralx")


@pytest.mark.parametrize(
    ("status", "hard"),
    [(400, False), (413, False), (422, False), (401, True), (402, True), (429, True), (503, True)],
)
async def test_the_real_attempt_sorts_http_statuses_into_hard_and_soft(monkeypatch, status, hard):
    import httpx

    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(status, text="no")), **kw
        ),
    )
    p = llm.providers()[0]
    with pytest.raises(llm.ProviderError) as e:
        [d async for d in llm._attempt(p, [], None, llm.Turn())]
    assert e.value.hard is hard


async def test_a_network_error_is_a_hard_failure(monkeypatch):
    import httpx

    def boom(request):
        raise httpx.ConnectError("down")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(boom), **kw)
    )
    with pytest.raises(llm.ProviderError) as e:
        [d async for d in llm._attempt(llm.providers()[0], [], None, llm.Turn())]
    assert e.value.hard is True


async def test_the_turn_says_which_provider_answered(monkeypatch):
    monkeypatch.setattr(llm, "_attempt", failing({"openrouter": HARD}))
    _, turn = await run()
    assert turn.usage["provider"] == "astralx"


async def test_the_guard_does_not_call_a_provider_that_is_resting(monkeypatch):
    llm._down["openrouter"] = time.monotonic() + 60

    def boom(*a, **k):
        raise AssertionError("the guard called a resting provider")

    monkeypatch.setattr(guard.httpx, "AsyncClient", boom)
    assert await guard.unsafe("how do I steal power?") is None


def test_the_answer_records_which_providers_its_rounds_came_from():
    from app.modules.copilot.services.chat import Answer

    a = Answer("vi")
    a.count({"prompt_tokens": 5, "provider": "openrouter", "cost": 0.5})
    a.count({"completion_tokens": 2, "provider": "astralx"})
    a.count({"completion_tokens": 1, "provider": "astralx"})
    assert a.usage["providers"] == ["openrouter", "astralx"] and a.usage["cost"] == 0.5


@pytest.mark.parametrize(
    ("code", "hard"), [(400, False), (422, False), (429, True), (503, True), (None, True)]
)
async def test_an_error_chunk_inside_a_200_stream_is_sorted_by_its_code(monkeypatch, code, hard):
    import json

    import httpx

    err = {"message": "x", **({"code": code} if code else {})}
    sse = "data: " + json.dumps({"error": err}) + "\n\n"
    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=sse.encode())), **kw
        ),
    )
    with pytest.raises(llm.ProviderError) as e:
        [d async for d in llm._attempt(llm.providers()[0], [], None, llm.Turn())]
    assert e.value.hard is hard


async def test_openrouter_is_asked_to_keep_and_train_on_nothing(monkeypatch):
    import json

    import httpx

    from app.modules.copilot.services import documents

    zdr = {"zdr": True, "data_collection": "deny"}
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "astralx_api_key", "k")
    by_name = {p.name: p for p in llm.providers()}
    assert by_name["openrouter"].extra["provider"] == zdr
    assert "provider" not in by_name["astralx"].extra  # not an OpenRouter field

    bodies = []

    def answer(request):
        bodies.append((request.url.host, json.loads(request.content)))
        if request.url.path.endswith("/embeddings"):
            n = len(bodies[-1][1]["input"])
            return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1024}] * n})
        return httpx.Response(200, json={"choices": [{"message": {"content": "safe"}}]})

    real = httpx.AsyncClient
    for module in (guard, documents):
        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(answer), **kw),
        )
    await guard.unsafe("Hôm nay bao nhiêu kWh?")
    await documents._call(settings.openrouter_base_url, "k", "m", ["x"])
    await documents._call(settings.astralx_base_url, "k", "m", ["x"])
    assert [b.get("provider") for _, b in bodies] == [zdr, zdr, None]
