from types import SimpleNamespace

from persona_bot.bot import JCVDBot
from persona_bot.config import CLAUDE_MODEL, MAX_HISTORY_TURNS, OLLAMA_MODEL

CITATION = {"id": "quote_001", "text": "Je suis aware.", "similarity": 0.5, "themes": [], "tone": ""}


class FakeRetriever:
    def search(self, query):
        return [CITATION]


class FakeClient:
    """
    Imite le SDK Anthropic et enregistre chaque appel.
    Claude passe par client.beta.messages.create, Ollama par client.messages.create :
    `endpoints` garde la trace de celui qui a été utilisé.
    """

    def __init__(self, stop_reason="end_turn"):
        self.calls = []
        self.endpoints = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self.create("beta", **kw)))
        self.messages = SimpleNamespace(create=lambda **kw: self.create("standard", **kw))

    def create(self, endpoint, **kwargs):
        self.endpoints.append(endpoint)
        self.calls.append(kwargs)
        text = SimpleNamespace(type="text", text=f"réponse {len(self.calls)}")
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason=self.stop_reason,
            content=[text],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


def make_bot(backend="claude", **client_kwargs):
    client = FakeClient(**client_kwargs)
    return JCVDBot(retriever=FakeRetriever(), client=client, backend=backend), client


def test_citations_are_sent_but_not_stored_in_history():
    bot, client = make_bot()
    answer, citations = bot.respond("J'ai peur d'échouer", conversation_id="alice")

    assert answer == "réponse 1"
    assert citations == [CITATION]
    assert "Je suis aware." in client.calls[0]["messages"][-1]["content"]
    assert bot.histories["alice"] == [
        {"role": "user", "content": "J'ai peur d'échouer"},
        {"role": "assistant", "content": "réponse 1"},
    ]


def test_previous_turns_are_sent_back():
    bot, client = make_bot()
    bot.respond("premier", conversation_id="alice")
    bot.respond("second", conversation_id="alice")

    sent = client.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "premier"


def test_conversations_are_isolated():
    bot, client = make_bot()
    bot.respond("salut", conversation_id="alice")
    bot.respond("coucou", conversation_id="bob")

    assert len(client.calls[1]["messages"]) == 1
    assert len(bot.histories["alice"]) == len(bot.histories["bob"]) == 2


def test_history_is_trimmed_by_pairs():
    bot, _ = make_bot()
    for i in range(MAX_HISTORY_TURNS + 5):
        bot.respond(f"question {i}", conversation_id="alice")

    history = bot.histories["alice"]
    assert len(history) == 2 * MAX_HISTORY_TURNS
    assert history[0] == {"role": "user", "content": "question 5"}


def test_reset_forgets_the_conversation():
    bot, _ = make_bot()
    bot.respond("salut", conversation_id="alice")
    bot.reset("alice")
    assert "alice" not in bot.histories


def test_refusal_returns_an_in_character_message():
    bot, _ = make_bot(stop_reason="refusal")
    answer, _ = bot.respond("sujet refusé")
    assert "préfère pas en parler" in answer


def test_claude_backend_sends_claude_only_parameters():
    bot, client = make_bot(backend="claude")
    bot.respond("salut")
    assert client.endpoints == ["beta"]
    call = client.calls[0]
    assert call["model"] == CLAUDE_MODEL
    assert {"betas", "fallbacks", "output_config"} <= call.keys()


def test_ollama_backend_sends_a_plain_request():
    bot, client = make_bot(backend="ollama")
    answer, _ = bot.respond("salut")
    assert answer == "réponse 1"
    assert client.endpoints == ["standard"]
    call = client.calls[0]
    assert call["model"] == OLLAMA_MODEL
    assert not {"betas", "fallbacks", "output_config"} & call.keys()


def test_last_response_is_kept_for_metrics():
    bot, _ = make_bot()
    bot.respond("salut")
    assert bot.last_response.usage.output_tokens == 20
