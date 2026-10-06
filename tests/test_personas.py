import pytest

from persona_bot.cli import telegram_tokens
from persona_bot.personas import PersonaError, list_personas, load_persona

VALID = """
name = "Testeur"
system_prompt = '''Tu es un personnage de test.'''

[messages]
welcome = "Bienvenue"
reset = "On recommence"
refusal = "Non"
rate_limit = "Doucement"
api_error = "Erreur"
connection_error = "Pas de connexion"
farewell = "Au revoir"
"""


def write_persona(personas_dir, slug, content=VALID, citations=None):
    directory = personas_dir / slug
    directory.mkdir(parents=True)
    (directory / "persona.toml").write_text(content, encoding="utf-8")
    if citations is not None:
        (directory / "citations.md").write_text(citations, encoding="utf-8")


def test_load_persona_without_citations(tmp_path):
    write_persona(tmp_path, "test")
    persona = load_persona("test", tmp_path)
    assert persona.name == "Testeur"
    assert persona.messages["farewell"] == "Au revoir"
    assert not persona.has_citations
    assert persona.collection_name == "citations_test"
    assert persona.ingest.themes == {}  # section [ingest] facultative


def test_citations_file_enables_rag(tmp_path):
    write_persona(tmp_path, "test", citations="> Une citation\n")
    assert load_persona("test", tmp_path).has_citations


def test_missing_fields_are_all_reported(tmp_path):
    write_persona(
        tmp_path, "test", VALID.replace('farewell = "Au revoir"', "").replace('name = "Testeur"', "")
    )
    with pytest.raises(PersonaError, match="name, messages.farewell"):
        load_persona("test", tmp_path)


def test_unknown_persona_lists_the_available_ones(tmp_path):
    write_persona(tmp_path, "alice")
    with pytest.raises(PersonaError, match="Personas disponibles : alice"):
        load_persona("bob", tmp_path)


def test_slug_must_be_usable_in_an_environment_variable(tmp_path):
    with pytest.raises(PersonaError, match="invalide"):
        load_persona("jean-claude", tmp_path)


def test_unknown_ingest_key_is_reported(tmp_path):
    write_persona(tmp_path, "test", VALID + "\n[ingest]\ntheme = {}\n")
    with pytest.raises(PersonaError, match=r"\[ingest\]"):
        load_persona("test", tmp_path)


def test_list_personas(tmp_path):
    write_persona(tmp_path, "b")
    write_persona(tmp_path, "a")
    (tmp_path / "pas_une_persona").mkdir()  # dossier sans persona.toml : ignoré
    assert list_personas(tmp_path) == ["a", "b"]


def test_real_personas_load():
    # Les vraies personas du dépôt doivent rester valides.
    for slug in list_personas():
        load_persona(slug)
    assert load_persona("jcvd").has_citations


def test_telegram_tokens_skip_personas_without_token():
    environ = {"TELEGRAM_TOKEN_JCVD": "111:aaa"}
    assert telegram_tokens(["jcvd", "autre"], environ) == [("jcvd", "111:aaa")]


def test_telegram_tokens_explain_the_old_variable():
    with pytest.raises(SystemExit, match="TELEGRAM_TOKEN_JCVD"):
        telegram_tokens(["jcvd"], {"TELEGRAM_BOT_TOKEN": "111:aaa"})


def test_telegram_tokens_must_be_distinct():
    environ = {"TELEGRAM_TOKEN_A": "111:aaa", "TELEGRAM_TOKEN_B": "111:aaa"}
    with pytest.raises(SystemExit, match="même token"):
        telegram_tokens(["a", "b"], environ)
