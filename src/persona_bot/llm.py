"""
Étape 3b (génération) : parler au modèle de langage, Claude ou un modèle local via Ollama.

Le RAG ne dépend pas du modèle de langage : la recherche des citations est la même, seul
change le programme qui écrit la réponse. Ce module isole tout ce qui dépend de ce choix.

Pourquoi un seul SDK pour les deux ?
Ollama expose une API compatible avec celle d'Anthropic (la route /v1/messages). Le client
Python d'Anthropic fonctionne donc avec Ollama en changeant seulement son adresse. On lui
donne une clé factice : le SDK en exige une, Ollama l'ignore.

Ce qui diffère :
- Claude accepte des paramètres qui lui sont propres (effort, repli automatique en cas de
  refus). Ollama les ignorerait sans rien dire ; on ne les envoie donc pas, pour que le code
  dise exactement ce qui est utilisé.
- Un modèle local a une fenêtre de contexte (la quantité de texte lue d'un coup) bien plus
  petite. Si le prompt système, les citations et l'historique la dépassent, Ollama tronque
  le début sans erreur : le bot perdrait sa personnalité. On règle cette taille côté serveur
  (OLLAMA_CONTEXT_LENGTH, voir README) et on la vérifie avec `persona --debug`.
"""

import logging

import anthropic

from persona_bot.config import (
    CLAUDE_MODEL,
    MAX_RESPONSE_TOKENS,
    OLLAMA_BASE_URL,
    OLLAMA_MAX_TOKENS,
    OLLAMA_MODEL,
)
from persona_bot.logs import traced

log = logging.getLogger(__name__)

BACKENDS = ("claude", "ollama")


def check_backend(backend):
    if backend not in BACKENDS:
        raise ValueError(f"LLM_BACKEND={backend!r} inconnu : valeurs possibles {', '.join(BACKENDS)}")


def model_name(backend):
    check_backend(backend)
    return CLAUDE_MODEL if backend == "claude" else OLLAMA_MODEL


def total_input_tokens(usage):
    """
    Nombre total de tokens lus par le modèle pour cette requête.

    `input_tokens` ne compte que la partie *nouvelle* de la requête : le début déjà lu lors
    d'un appel précédent (prompt système, historique) est compté à part dans les champs de
    cache. Ollama et Claude remplissent ces champs de la même façon. C'est ce total qu'il faut
    comparer à la fenêtre de contexte.
    """
    return (
        usage.input_tokens
        + (getattr(usage, "cache_read_input_tokens", None) or 0)
        + (getattr(usage, "cache_creation_input_tokens", None) or 0)
    )


@traced
def create_client(backend):
    check_backend(backend)
    if backend == "claude":
        # Sans argument, le SDK lit la clé dans la variable ANTHROPIC_API_KEY.
        return anthropic.Anthropic()
    log.debug("Client Ollama sur %s", OLLAMA_BASE_URL)
    return anthropic.Anthropic(base_url=OLLAMA_BASE_URL, api_key="ollama")


@traced
def generate(client, backend, system, messages):
    """Envoie la conversation au modèle et renvoie sa réponse (même forme pour les deux backends)."""
    check_backend(backend)
    if backend == "claude":
        return client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system,
            messages=messages,
            # Une conversation n'a pas besoin de réflexion poussée : effort bas = plus rapide et moins cher.
            output_config={"effort": "low"},
            # Si le modèle refuse une requête par sécurité, l'API bascule sur un autre modèle.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    return client.messages.create(
        model=OLLAMA_MODEL,
        max_tokens=OLLAMA_MAX_TOKENS,
        system=system,
        messages=messages,
    )
