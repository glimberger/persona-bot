from persona_bot.evaluation import evaluate, load_eval_set, rank_of_expected, summarize
from persona_bot.personas import load_persona


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


def test_eval_set_is_well_formed():
    eval_set = load_eval_set(load_persona("jcvd").eval_json)
    assert {e["level"] for e in eval_set} == {"facile", "difficile"}
    assert all(e["question"] and e["expected"] for e in eval_set)
