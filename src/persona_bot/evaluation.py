"""
Évaluer la recherche de citations (l'étape "Retrieval" du RAG).

Sans mesure, impossible de savoir si une modification (autre modèle d'embeddings, autre seuil,
citations enrichies...) améliore ou dégrade la recherche. On utilise un jeu d'évaluation,
data/eval_search.json : des questions, et pour chacune les citations qui y répondent
(repérées par un fragment de leur texte, plus stable qu'un identifiant).

Deux indicateurs :
- hit@3 : la bonne citation est-elle parmi les 3 que le bot reçoit réellement ?
- MRR (Mean Reciprocal Rank, rang réciproque moyen) : 1 si la bonne citation est 1re,
  1/2 si 2e, 1/3 si 3e... 0 si absente du top 10. Récompense une citation bien placée.

Les questions sont classées par niveau :
- "facile"    : elles reprennent des mots de la citation attendue ;
- "difficile" : elles sont indirectes, comme un vrai utilisateur qui ne connaît pas les citations.
Un jeu uniquement "facile" donne un score flatteur qui ne mesure presque rien.
"""

import json
import logging

from persona_bot.config import RETRIEVE_K
from persona_bot.logs import traced

log = logging.getLogger(__name__)

TOP_N = 10  # profondeur de recherche pour calculer le rang


def load_eval_set(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rank_of_expected(texts, expected_fragments):
    """Rang (à partir de 1) de la première citation attendue dans `texts`, ou None si absente."""
    for rank, text in enumerate(texts, start=1):
        if any(fragment in text for fragment in expected_fragments):
            return rank
    return None


def summarize(results, k=RETRIEVE_K):
    """results : liste de (niveau, rang). Renvoie {niveau: {"hit": ..., "total": ..., "mrr": ...}}."""
    summary = {}
    for level, rank in results:
        s = summary.setdefault(level, {"hit": 0, "total": 0, "mrr": 0.0})
        s["total"] += 1
        s["hit"] += rank is not None and rank <= k
        s["mrr"] += 1 / rank if rank else 0.0
    for s in summary.values():
        s["mrr"] = round(s["mrr"] / s["total"], 2)
    return summary


@traced
def evaluate(retriever, eval_set):
    """Renvoie une liste de (entrée du jeu d'évaluation, rang de la bonne citation)."""
    results = []
    for entry in eval_set:
        # threshold=-1 : on veut le classement complet, sans filtrage par le seuil de similarité.
        found = retriever.search(entry["question"], k=TOP_N, threshold=-1)
        rank = rank_of_expected([c["text"] for c in found], entry["expected"])
        log.debug("Rang %s pour %r", rank, entry["question"])
        results.append((entry, rank))
    return results
