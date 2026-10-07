from types import SimpleNamespace

import pytest

from persona_bot import retriever
from persona_bot.personas import PersonaError


class EmptyChromaClient:
    """Une base Chroma sans aucune collection : ce qu'on a après un `git pull` sans `persona index`."""

    def list_collections(self):
        return []


class ChromaClientWith:
    def __init__(self, *names):
        self.names = names

    def list_collections(self):
        return [SimpleNamespace(name=name) for name in self.names]

    def get_collection(self, name, embedding_function):
        return SimpleNamespace(count=lambda: 3)


def no_model():
    raise AssertionError("le modèle d'embeddings ne doit pas être chargé")


def test_missing_index_gives_a_clear_error_without_loading_the_model(persona, monkeypatch):
    monkeypatch.setattr(retriever, "get_client", EmptyChromaClient)
    monkeypatch.setattr(retriever, "embedding_function", no_model)

    with pytest.raises(PersonaError, match="uv run persona index test"):
        retriever.Retriever(persona)


def test_existing_index_is_opened(persona, monkeypatch):
    monkeypatch.setattr(retriever, "get_client", lambda: ChromaClientWith("citations_test"))
    monkeypatch.setattr(retriever, "embedding_function", lambda: None)

    assert retriever.Retriever(persona).collection.count() == 3
