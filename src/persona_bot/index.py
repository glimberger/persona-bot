"""
Étape 2 : vectoriser les citations et les indexer dans Chroma.

Chaque citation est transformée en vecteur de 384 nombres par un modèle
d'embeddings local (sentence-transformers). Deux textes de sens proche donnent
des vecteurs proches : c'est ce qui permet la recherche "par le sens".

Chaque persona qui a des citations a sa propre collection Chroma (citations_<slug>),
dans la même base data/chroma/. À relancer uniquement quand ses citations changent.
"""

import functools
import json
import logging

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from persona_bot.config import CHROMA_DB_PATH, EMBEDDING_MODEL
from persona_bot.logs import traced

log = logging.getLogger(__name__)


# functools.cache garde le résultat du premier appel et le renvoie ensuite sans recalculer.
# Le modèle d'embeddings (plusieurs centaines de Mo en mémoire) n'est ainsi chargé qu'une fois,
# même quand plusieurs personas tournent dans le même processus (`persona telegram`).
# @traced est placé au-dessus : seul le premier appel exécute vraiment la fonction, mais
# chaque appel reste visible dans les logs.
@traced
@functools.cache
def embedding_function():
    log.debug("Chargement du modèle d'embeddings %s", EMBEDDING_MODEL)
    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


@traced
@functools.cache
def get_client():
    return chromadb.PersistentClient(path=str(CHROMA_DB_PATH))


@traced
def build_index(persona):
    """data/<slug>/citations.json -> collection Chroma citations_<slug>."""
    citations = json.loads(persona.citations_json.read_text(encoding="utf-8"))
    log.debug("%d citations lues dans %s", len(citations), persona.citations_json)

    client = get_client()
    name = persona.collection_name
    # On reconstruit l'index de zéro : simple et toujours cohérent avec le JSON.
    if name in [c.name for c in client.list_collections()]:
        log.debug("Suppression de l'ancienne collection %r", name)
        client.delete_collection(name)

    collection = client.create_collection(
        name=name,
        embedding_function=embedding_function(),
        # Par défaut Chroma mesure une distance L2 ; on veut la distance cosinus
        # pour que "1 - distance" soit bien une similarité cosinus.
        configuration={"hnsw": {"space": "cosine"}},
    )
    log.debug("Vectorisation et ajout de %d documents (modèle %s)", len(citations), EMBEDDING_MODEL)
    collection.add(
        ids=[c["id"] for c in citations],
        documents=[c["text"] for c in citations],
        # Chroma n'accepte pas de listes en métadonnées : on les joint par "|".
        metadatas=[
            {"themes": "|".join(c["themes"]), "tone": c["tone"], "length": c["length"]} for c in citations
        ],
    )
    return collection.count()
