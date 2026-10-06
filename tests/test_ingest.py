from persona_bot.ingest import build_citations, classify, deduplicate, extract_quotes, normalize
from persona_bot.personas import IngestRules, load_persona

JCVD = load_persona("jcvd")
RULES = IngestRules(
    themes={"nature": ["air", "eau"]},
    contexts={"nature": "quand on parle de nature"},
    default_theme="sagesse",
    default_context="sagesse générale",
)


def test_extract_quotes_joins_multiline_blocks():
    markdown = "Sources :\n- un lien\n\n>Première ligne\nsuite de la citation\n\n>Deuxième\n"
    assert extract_quotes(markdown) == ["Première ligne suite de la citation", "Deuxième"]


def test_normalize_ignores_accents_case_and_punctuation():
    assert normalize("Je suis fasciné par l'air....") == normalize("je suis fascine par l air")


def test_deduplicate_removes_near_duplicates_and_keeps_first():
    quotes = [
        "Je suis fascine par l'air. En meme temps l'air tu peux pas le toucher.",
        "Je suis fasciné par l'air. En même temps, l'air, tu ne peux pas le toucher.",
        "Ma devise, c'est : il faut se recréer, pour recréer !",
    ]
    assert deduplicate(quotes) == [quotes[0], quotes[2]]


def test_classify_matches_whole_words_only():
    # "faire" contient "air" et "beau" contient "eau" : ce ne sont pas des thèmes "nature".
    assert "nature" not in classify("Il faut faire quelque chose de beau.", RULES)["themes"]
    assert "nature" in classify("L'air, c'est un peu comme mon cerveau.", RULES)["themes"]


def test_classify_defaults():
    result = classify("Quand j'étais jeune, j'étais très con.", RULES)
    assert result["themes"] == ["sagesse"]
    assert result["search_contexts"] == ["sagesse générale"]
    assert result["length"] == "aphorisme"
    assert result["tone"] == "affirmatif"


def test_real_corpus():
    raw_count, citations = build_citations(JCVD.citations_md.read_text(encoding="utf-8"), JCVD.ingest)
    assert raw_count == 89
    assert len(citations) == 72
    assert len({c["id"] for c in citations}) == len(citations)


def test_contexts_follow_the_themes():
    result = classify("L'eau, c'est la vie.", RULES)
    assert result["themes"] == ["nature"]
    assert result["search_contexts"] == ["quand on parle de nature"]
