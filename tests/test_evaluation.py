import json

import pytest

from persona_bot.evaluation import evaluate, load_eval_set, rank_of_expected, summarize
from persona_bot.personas import list_personas, load_persona


def test_rank_of_expected():
    texts = ["Je suis aware.", "J'adore les cacahuètes.", "L'air, c'est magique."]
    assert rank_of_expected(texts, ["cacahuètes"]) == 2
    assert rank_of_expected(texts, ["pomme", "air"]) == 3
    assert rank_of_expected(texts, ["pomme"]) is None


def test_summarize_computes_hit_and_mrr_per_level():
    summary = summarize([("facile", 1), ("facile", 2), ("difficile", 4), ("difficile", None)], k=3)
    assert summary["facile"] == {"hit": 2, "total": 2, "mrr": 0.75}
    assert summary["difficile"] == {"hit": 0, "total": 2, "mrr": 0.12}


class FakeRetriever:
    def search(self, query, k, threshold):
        return [{"text": "autre"}, {"text": "La bonne citation"}]


def test_evaluate_uses_the_retriever_ranking():
    eval_set = [{"question": "q", "expected": ["bonne"], "level": "facile"}]
    [(entry, rank)] = evaluate(FakeRetriever(), eval_set)
    assert entry["question"] == "q" and rank == 2


def personas_with_eval_set():
    personas = [load_persona(slug) for slug in list_personas()]
    return [p for p in personas if p.eval_json.exists()]


@pytest.mark.parametrize("persona", personas_with_eval_set(), ids=lambda p: p.slug)
def test_eval_set_is_well_formed(persona):
    eval_set = load_eval_set(persona.eval_json)
    assert {e["level"] for e in eval_set} == {"facile", "difficile"}
    assert all(e["question"] and e["expected"] for e in eval_set)


@pytest.mark.parametrize("persona", personas_with_eval_set(), ids=lambda p: p.slug)
def test_expected_fragments_exist_in_the_citations(persona):
    # Un fragment qui ne correspond à aucune citation (faute de frappe, citation modifiée)
    # compterait toujours comme un échec : le score baisserait sans que la recherche change.
    texts = [c["text"] for c in json.loads(persona.citations_json.read_text(encoding="utf-8"))]
    missing = [
        f for e in load_eval_set(persona.eval_json) for f in e["expected"] if not any(f in t for t in texts)
    ]
    assert missing == []
