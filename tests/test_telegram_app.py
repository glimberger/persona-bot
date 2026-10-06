import asyncio
import logging
import time
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from telegram import Update
from telegram.error import Conflict

from persona_bot import telegram_app
from persona_bot.telegram_app import (
    build_application,
    is_allowed,
    on_error,
    on_message,
    parse_allowed_users,
    reset,
    split_message,
)

ALLOWED_ID = 42


class FakeJCVD:
    def __init__(self, answer="Ah tu vois...", error=None, delay=0):
        self.answer, self.error, self.delay = answer, error, delay
        self.resets = []

    def respond(self, text, conversation_id):
        # Simule un modèle lent (Ollama sur le Pi) : bloquant, comme le vrai respond().
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer, []

    def reset(self, conversation_id):
        self.resets.append(conversation_id)


def run_handler(handler, jcvd, user_id=ALLOWED_ID, text="salut", events=None):
    """
    Appelle un handler avec de faux objets Telegram et renvoie les messages envoyés.

    `events`, si fourni, reçoit dans l'ordre les messages et les indicateurs « en train
    d'écrire » ("typing").
    """
    sent = []
    events = [] if events is None else events

    async def reply_text(message):
        sent.append(message)
        events.append(message)

    async def send_chat_action(*args):
        events.append("typing")

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, full_name="Test"),
        effective_chat=SimpleNamespace(id=user_id),
        message=SimpleNamespace(text=text, reply_text=reply_text),
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(send_chat_action=send_chat_action),
        bot_data={"jcvd": jcvd, "allowed_users": {ALLOWED_ID}},
    )
    asyncio.run(handler(update, context))
    return sent


def test_parse_allowed_users():
    assert parse_allowed_users("123, 456,") == {123, 456}
    assert parse_allowed_users("") == set()


def test_split_message():
    assert [len(p) for p in split_message("x" * 9000)] == [4096, 4096, 808]
    assert split_message("court") == ["court"]


def test_allowed_user_gets_an_answer():
    assert run_handler(on_message, FakeJCVD()) == ["Ah tu vois..."]


def test_unknown_user_is_ignored():
    assert run_handler(on_message, FakeJCVD(), user_id=999) == []


def test_api_error_gives_an_in_character_message():
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    [answer] = run_handler(on_message, FakeJCVD(error=error))
    assert "connecter" in answer


@pytest.fixture
def fast_typing():
    """Renvoie l'indicateur toutes les 10 ms au lieu de 4 s, pour des tests rapides."""
    normal = telegram_app.TYPING_REFRESH_SECONDS
    telegram_app.TYPING_REFRESH_SECONDS = 0.01
    yield
    telegram_app.TYPING_REFRESH_SECONDS = normal


def test_typing_indicator_lasts_until_the_answer(fast_typing):
    # Réponse lente : l'indicateur doit être renvoyé plusieurs fois, puis s'arrêter avant
    # l'envoi de la réponse.
    events = []
    run_handler(on_message, FakeJCVD(delay=0.1), events=events)
    assert events.count("typing") >= 3
    assert events[-1] == "Ah tu vois..."


def test_typing_indicator_stops_on_error(fast_typing):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "http://localhost:11434"))
    events = []
    run_handler(on_message, FakeJCVD(error=error, delay=0.05), events=events)
    assert "typing" in events
    assert "connecter" in events[-1]


def test_reset_command():
    jcvd = FakeJCVD()
    [answer] = run_handler(reset, jcvd)
    assert jcvd.resets == [ALLOWED_ID]
    assert "zéro" in answer


def test_conflict_error_gives_a_short_explanation(caplog):
    context = SimpleNamespace(error=Conflict("terminated by other getUpdates request"))
    with caplog.at_level(logging.INFO, logger="persona_bot"):
        asyncio.run(on_error(None, context))
    assert "autre instance du bot" in caplog.text
    assert "Traceback" not in caplog.text


FAKE_TOKEN = "123456789:AAH" + "x" * 32  # même format qu'un vrai token


def test_token_never_logged_by_traced_handlers(caplog):
    # Le Bot affiche son token dans sa représentation texte ("ExtBot[token=...]").
    # Ce faux contexte contient le bot : sans masquage, le token partirait dans les logs.
    app = build_application(FAKE_TOKEN, {ALLOWED_ID}, jcvd=FakeJCVD())
    data = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "text": "salut",
            "chat": {"id": ALLOWED_ID, "type": "private"},
            "from": {"id": ALLOWED_ID, "is_bot": False, "first_name": "Test"},
        },
    }
    update = Update.de_json(data, app.bot)
    context = SimpleNamespace(bot=app.bot, bot_data=app.bot_data)
    with caplog.at_level(logging.DEBUG, logger="persona_bot"):
        assert is_allowed(update, context)
    assert "→ is_allowed(update=Update(" in caplog.text
    assert "ExtBot[token=***]" in caplog.text
    assert "AAHxxx" not in caplog.text
