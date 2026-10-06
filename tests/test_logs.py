import asyncio
import logging
from types import SimpleNamespace

import pytest

from persona_bot.logs import short_repr, traced
from persona_bot.telegram_app import build_application


@traced
def add(a, b):
    return a + b


@traced
async def async_add(a, b):
    return a + b


@traced
def boom():
    raise ValueError("raté")


def test_traced_logs_call_and_result_in_debug(caplog):
    with caplog.at_level(logging.DEBUG, logger=__name__):
        assert add(2, b=3) == 5
    assert "→ add(a=2, b=3)" in caplog.text
    assert "← add = 5" in caplog.text


def test_traced_is_silent_outside_debug(caplog):
    with caplog.at_level(logging.INFO, logger=__name__):
        assert add(2, 3) == 5
    assert caplog.text == ""


def test_traced_supports_async_functions(caplog):
    with caplog.at_level(logging.DEBUG, logger=__name__):
        assert asyncio.run(async_add(1, 1)) == 2
    assert "← async_add = 2" in caplog.text


def test_traced_logs_and_reraises_errors(caplog):
    with caplog.at_level(logging.DEBUG, logger=__name__), pytest.raises(ValueError):
        boom()
    assert "✗ boom a levé ValueError" in caplog.text


def test_telegram_token_never_logged(caplog, persona):
    with caplog.at_level(logging.DEBUG, logger="persona_bot"):
        build_application("123456:TOKEN-SECRET", {42}, bot=SimpleNamespace(persona=persona))
    assert "Application Telegram prête" in caplog.text
    assert "TOKEN-SECRET" not in caplog.text


def test_short_repr_masks_secrets_even_in_long_values():
    token = "123456789:AAH" + "x" * 32
    key = "sk-ant-api03-" + "y" * 40
    text = short_repr({"texte": "a" * 300 + token, "cle": key})
    assert "xxxxxxxx" not in text and "yyyyyyyy" not in text
    assert short_repr(f"Bot[token={token}]") == "'Bot[token=***]'"
