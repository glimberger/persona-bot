"""
Étape 2 : vectoriser les citations et les indexer dans Chroma.

Chaque citation est transformée en vecteur de 384 nombres par un modèle
d'embeddings local (sentence-transformers). Deux textes de sens proche donnent
des vecteurs proches : c'est ce qui permet la recherche "par le sens".

À relancer uniquement quand les citations changent.
"""

import json
import logging
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from persona_bot.config import CHROMA_DB_PATH, COLLECTION_NAME, EMBEDDING_MODEL
from persona_bot.logs import traced

log = logging.getLogger(__name__)


@traced
def embedding_function():
    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


@traced
def get_client():
    return chromadb.PersistentClient(path=str(CHROMA_DB_PATH))


@traced
def build_index(citations_json: Path):
    citations = json.loads(citations_json.read_text(encoding="utf-8"))
    log.debug("%d citations lues dans %s", len(citations), citations_json)

    client = get_client()
    # On reconstruit l'index de zéro : simple et toujours cohérent avec le JSON.
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        log.debug("Suppression de l'ancienne collection %r", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
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
