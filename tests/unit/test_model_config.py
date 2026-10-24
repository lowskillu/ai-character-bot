"""Model ids and sampling are configuration now, not literals in handlers.

Two things worth pinning. First, the defaults: they were extracted from
hard-coded values, and a typo in a default would silently point production at a
different (or nonexistent) model. Second, that the env var actually wins —
otherwise the knob looks configurable and is not, which is worse than a literal.
"""

import importlib

import pytest


DEFAULTS = {
    "openrouter": {
        "CHAT_MODEL": "meta-llama/llama-3.3-70b-instruct",
        "PROMPT_MODEL": "meta-llama/llama-3.3-70b-instruct",
        "CHAT_TEMPERATURE": 0.9,
        "CHAT_MAX_TOKENS": 1000,
        "PROMPT_TEMPERATURE": 0.7,
        "PROMPT_MAX_TOKENS": 4000,
        "MAX_HISTORY_LENGTH": 5,
        "API_URL": "https://openrouter.ai/api/v1/chat/completions",
    },
    "runware": {
        "MODEL_ANIME": "runware:101@1",
        "MODEL_REALISTIC": "runware:101@1",
        "IMAGE_WIDTH": 1024,
        "IMAGE_HEIGHT": 1024,
        "IMAGE_STEPS": 20,
        "IMAGE_CFG_SCALE": 7.5,
        "DEFAULT_TIMEOUT": 60,
    },
}


def _fresh(module_name: str, monkeypatch, **env):
    """Re-import the module with a clean environment plus the given overrides."""
    for key in (
        "CHAT_MODEL", "PROMPT_MODEL", "CHAT_TEMPERATURE", "CHAT_MAX_TOKENS",
        "PROMPT_TEMPERATURE", "PROMPT_MAX_TOKENS", "MAX_HISTORY_LENGTH",
        "OPENROUTER_API_URL", "IMAGE_MODEL_ANIME", "IMAGE_MODEL_REALISTIC",
        "IMAGE_WIDTH", "IMAGE_HEIGHT", "IMAGE_STEPS", "IMAGE_CFG_SCALE",
        "RUNWARE_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(importlib.import_module(f"tgbot.services.{module_name}"))


@pytest.mark.parametrize("module_name", sorted(DEFAULTS))
def test_defaults_match_what_the_bot_shipped_with(module_name, monkeypatch):
    module = _fresh(module_name, monkeypatch)
    for name, expected in DEFAULTS[module_name].items():
        assert getattr(module, name) == expected, f"{module_name}.{name} drifted"


def test_chat_model_is_overridable(monkeypatch):
    module = _fresh("openrouter", monkeypatch, CHAT_MODEL="anthropic/claude-sonnet-4")
    assert module.CHAT_MODEL == "anthropic/claude-sonnet-4"


def test_prompt_model_is_overridable(monkeypatch):
    module = _fresh("openrouter", monkeypatch, PROMPT_MODEL="some/other-model")
    assert module.PROMPT_MODEL == "some/other-model"


def test_image_models_are_overridable(monkeypatch):
    module = _fresh(
        "runware", monkeypatch,
        IMAGE_MODEL_ANIME="civitai:1@2", IMAGE_MODEL_REALISTIC="civitai:3@4",
    )
    assert module.model_for_style("anime") == "civitai:1@2"
    assert module.model_for_style("realistic") == "civitai:3@4"


@pytest.mark.parametrize("style", [None, "", "bogus", "ANIME", "Realistic"])
def test_style_lookup_never_raises_and_falls_back_to_anime(style, monkeypatch):
    module = _fresh("runware", monkeypatch)
    expected = module.MODEL_REALISTIC if (style or "").lower() == "realistic" else module.MODEL_ANIME
    assert module.model_for_style(style) == expected


def test_headers_carry_auth_and_attribution(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("SITE_NAME", "Probe")
    module = _fresh("openrouter", monkeypatch)
    headers = module.headers()
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["X-Title"] == "Probe"
    assert headers["Content-Type"] == "application/json"


def test_numeric_settings_are_parsed_not_left_as_strings(monkeypatch):
    """A string where the API expects a number is a 400 from the provider."""
    module = _fresh("openrouter", monkeypatch, CHAT_TEMPERATURE="0.3", CHAT_MAX_TOKENS="512")
    assert module.CHAT_TEMPERATURE == 0.3 and isinstance(module.CHAT_TEMPERATURE, float)
    assert module.CHAT_MAX_TOKENS == 512 and isinstance(module.CHAT_MAX_TOKENS, int)


@pytest.fixture(autouse=True)
def _restore_modules():
    """Leave the imported modules holding the real environment again."""
    yield
    for name in ("openrouter", "runware"):
        importlib.reload(importlib.import_module(f"tgbot.services.{name}"))
