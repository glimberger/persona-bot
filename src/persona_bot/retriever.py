"""
Étape 3a : retrouver les citations les plus proches d'une question.

La question est vectorisée avec LE MÊME modèle que les citations (sinon les
vecteurs ne sont pas comparables), puis Chroma renvoie les plus proches.

Un Retriever ne cherche que dans la collection de sa persona. Une persona sans
citations n'a pas de Retriever du tout (voir bot.py).
"""

import logging

from persona_bot.config import RETRIEVE_K, SIMILARITY_THRESHOLD
from persona_bot.index import embedding_function, get_client
from persona_bot.logs import short_repr, traced

log = logging.getLogger(__name__)


class Retriever:
    @traced
    def __init__(self, persona):
        name = persona.collection_name
        self.collection = get_client().get_collection(name=name, embedding_function=embedding_function())
        log.debug("Collection %r ouverte : %d citations", name, self.collection.count())

    @traced
    def search(self, query, k=RETRIEVE_K, threshold=SIMILARITY_THRESHOLD):
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        citations = []
        for id_, text, meta, distance in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            strict=True,
        ):
            similarity = 1 - distance  # valable car la collection utilise la distance cosinus
            if similarity < threshold:
                log.debug("  écartée  %.3f < seuil %.2f  %s %s", similarity, threshold, id_, short_repr(text))
                continue
            log.debug("  retenue  %.3f              %s %s", similarity, id_, short_repr(text))
            citations.append(
                {
                    "id": id_,
                    "text": text,
                    "similarity": round(similarity, 3),
                    "themes": meta["themes"].split("|"),
                    "tone": meta["tone"],
                }
            )
        return citations
