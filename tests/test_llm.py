from types import SimpleNamespace

import pytest

from persona_bot import llm
from persona_bot.cli import answer_metrics
from persona_bot.config import OLLAMA_BASE_URL


def test_ollama_client_points_to_ollama_server():
    client = llm.create_client("ollama")
    assert str(client.base_url).rstrip("/") == OLLAMA_BASE_URL.rstrip("/")


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="LLM_BACKEND"):
        llm.create_client("gpt")
    with pytest.raises(ValueError, match="LLM_BACKEND"):
        llm.generate(client=None, backend="gpt", system="", messages=[])


def test_answer_metrics():
    text = "Tu vois, l'air... c'est magique et ça existe. Donc on respire, tu comprends ?"
    assert answer_metrics(text) == {"mots": 14, "phrases": 2, "finit par une question": True}


def test_total_input_tokens_includes_cache():
    usage = SimpleNamespace(input_tokens=1, cache_read_input_tokens=258, cache_creation_input_tokens=None)
    assert llm.total_input_tokens(usage) == 259
