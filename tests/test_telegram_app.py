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
    run_all,
    split_message,
    start,
)

ALLOWED_ID = 42


class FakeBot:
    """Remplace PersonaBot : même interface (persona, respond, reset), sans modèle."""

    def __init__(self, persona, answer="Ah tu vois...", error=None, delay=0):
        self.persona = persona
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


def run_handler(handler, bot, user_id=ALLOWED_ID, text="salut", events=None):
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
        bot_data={"bot": bot, "allowed_users": {ALLOWED_ID}},
    )
    asyncio.run(handler(update, context))
    return sent


def test_parse_allowed_users():
    assert parse_allowed_users("123, 456,") == {123, 456}
    assert parse_allowed_users("") == set()


def test_split_message():
    assert [len(p) for p in split_message("x" * 9000)] == [4096, 4096, 808]
    assert split_message("court") == ["court"]


def test_allowed_user_gets_an_answer(persona):
    assert run_handler(on_message, FakeBot(persona)) == ["Ah tu vois..."]


def test_unknown_user_is_ignored(persona):
    assert run_handler(on_message, FakeBot(persona), user_id=999) == []


def test_api_error_gives_an_in_character_message(persona):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    [answer] = run_handler(on_message, FakeBot(persona, error=error))
    assert answer == "message connection_error"


@pytest.fixture
def fast_typing():
    """Renvoie l'indicateur toutes les 10 ms au lieu de 4 s, pour des tests rapides."""
    normal = telegram_app.TYPING_REFRESH_SECONDS
    telegram_app.TYPING_REFRESH_SECONDS = 0.01
    yield
    telegram_app.TYPING_REFRESH_SECONDS = normal


def test_typing_indicator_lasts_until_the_answer(fast_typing, persona):
    # Réponse lente : l'indicateur doit être renvoyé plusieurs fois, puis s'arrêter avant
    # l'envoi de la réponse.
    events = []
    run_handler(on_message, FakeBot(persona, delay=0.1), events=events)
    assert events.count("typing") >= 3
    assert events[-1] == "Ah tu vois..."


def test_typing_indicator_stops_on_error(fast_typing, persona):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "http://localhost:11434"))
    events = []
    run_handler(on_message, FakeBot(persona, error=error, delay=0.05), events=events)
    assert "typing" in events
    assert events[-1] == "message connection_error"


def test_reset_command(persona):
    bot = FakeBot(persona)
    [answer] = run_handler(reset, bot)
    assert bot.resets == [ALLOWED_ID]
    assert answer == "message reset"


def test_conflict_error_gives_a_short_explanation(caplog):
    context = SimpleNamespace(error=Conflict("terminated by other getUpdates request"))
    with caplog.at_level(logging.INFO, logger="persona_bot"):
        asyncio.run(on_error(None, context))
    assert "autre instance du bot" in caplog.text
    assert "Traceback" not in caplog.text


FAKE_TOKEN = "123456789:AAH" + "x" * 32  # même format qu'un vrai token


def test_token_never_logged_by_traced_handlers(caplog, persona):
    # Le Bot affiche son token dans sa représentation texte ("ExtBot[token=...]").
    # Ce faux contexte contient le bot : sans masquage, le token partirait dans les logs.
    app = build_application(FAKE_TOKEN, {ALLOWED_ID}, bot=FakeBot(persona))
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


def test_start_command_sends_the_persona_welcome(persona):
    assert run_handler(start, FakeBot(persona)) == ["message welcome"]


class FakeApplication:
    """
    Imite une Application Telegram : enregistre dans `log` chaque étape de démarrage et
    d'arrêt, pour vérifier que run_all les enchaîne dans le bon ordre.
    """

    def __init__(self, name, log, persona, fail_on_initialize=False):
        self.name, self.log, self.fail = name, log, fail_on_initialize
        self.running = False
        self.bot = SimpleNamespace(username=name)
        self.bot_data = {"bot": FakeBot(persona)}
        app = self

        class Updater:
            running = False

            async def start_polling(self, error_callback):
                app.log.append(f"{app.name}.start_polling")
                self.running = True

            async def stop(self):
                app.log.append(f"{app.name}.updater.stop")
                self.running = False

        self.updater = Updater()

    async def initialize(self):
        self.log.append(f"{self.name}.initialize")
        if self.fail:
            raise RuntimeError("token invalide")

    async def start(self):
        self.log.append(f"{self.name}.start")
        self.running = True

    async def stop(self):
        self.log.append(f"{self.name}.stop")
        self.running = False

    async def shutdown(self):
        self.log.append(f"{self.name}.shutdown")


def run_until_stopped(applications):
    """Lance run_all, puis demande l'arrêt dès que tout a démarré."""

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(run_all(applications, stop=stop))
        await asyncio.sleep(0.01)  # laisse run_all démarrer les bots
        stop.set()
        await task

    asyncio.run(scenario())


def test_run_all_starts_every_bot_then_stops_them_in_reverse_order(persona):
    log = []
    run_until_stopped([FakeApplication("a", log, persona), FakeApplication("b", log, persona)])
    assert log == [
        "a.initialize", "a.start_polling", "a.start",
        "b.initialize", "b.start_polling", "b.start",
        "b.updater.stop", "b.stop", "b.shutdown",
        "a.updater.stop", "a.stop", "a.shutdown",
    ]  # fmt: skip


def test_run_all_stops_started_bots_when_another_fails(persona):
    # Le 2e bot a un token invalide : le 1er, déjà démarré, doit quand même s'arrêter proprement.
    log = []
    apps = [FakeApplication("a", log, persona), FakeApplication("b", log, persona, fail_on_initialize=True)]
    with pytest.raises(RuntimeError):
        run_until_stopped(apps)
    assert log[-4:] == ["b.shutdown", "a.updater.stop", "a.stop", "a.shutdown"]
    assert "b.start" not in log
