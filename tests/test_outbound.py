import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
GATE = {"config.py", "common/outbound.py"}
# What reaches outside: an address of its own, or the settings that hold one.
EXTERNAL = re.compile(
    r"https?://(?!localhost|127\.0\.0\.1)[^\s\"'/]+|"
    r"settings\.(?:openrouter_base_url|astralx_base_url|openweather_base_url|telegram_api_url|"
    r"text2sql_url)\b"
)
# Links shown to people under an answer (sources), never called; chat.py builds no client.
SHOWN = {
    "modules/copilot/services/chat.py": None,
    "modules/copilot/services/tools.py": {"https://vanban.chinhphu.vn"},
}


def test_external_addresses_live_only_in_config_and_the_gateway():
    found = set()
    for p in APP.rglob("*.py"):
        name = str(p.relative_to(APP))
        if name in GATE:
            continue
        for hit in EXTERNAL.findall(p.read_text()):
            allowed = SHOWN.get(name, set())
            if allowed is None or hit in allowed:
                continue
            found.add((name, hit))
    assert found == set(), "send through app.common.outbound, the one gate"


def test_the_file_of_shown_links_calls_nothing():
    assert "httpx" not in (APP / "modules/copilot/services/chat.py").read_text()
