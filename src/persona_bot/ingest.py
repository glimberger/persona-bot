"""
Étape 1 : transformer le Markdown brut en citations structurées.

1. Extraire les citations (blocs commençant par ">")
2. Supprimer les doublons, y compris les quasi-doublons : mêmes mots aux accents
   ou à la ponctuation près, ou versions presque identiques (similarité >= 90 %)
3. Ajouter des métadonnées simples (thèmes, ton, longueur)

Les métadonnées sont des heuristiques par mots-clés : utiles pour explorer
le corpus et donner du contexte au LLM, mais c'est l'embedding (étape 2)
qui fait le vrai travail de recherche par le sens. Les mots-clés dépendent
du vocabulaire de chaque persona : ils sont dans son persona.toml, section
[ingest] (voir personas.py).

Cette étape ne concerne que les personas qui ont des citations.
"""

import difflib
import json
import logging
import re
import unicodedata

from persona_bot.logs import short_repr, traced

log = logging.getLogger(__name__)

DUPLICATE_RATIO = 0.9


# contains_word et normalize ne sont pas décorées par @traced : elles sont appelées des
# milliers de fois par ingestion, leurs traces noieraient tout le reste.
def contains_word(text, word):
    """Vrai si `word` apparaît comme mot entier (évite "air" dans "faire")."""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def normalize(text):
    """Forme canonique pour détecter les doublons : sans accents ni ponctuation."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@traced
def extract_quotes(content):
    quotes, current = [], []
    for line in content.splitlines():
        if line.startswith(">"):
            current.append(line.lstrip(">").strip())
        elif line.strip() and current:
            current.append(line.strip())  # suite d'une citation sur plusieurs lignes
        elif current:
            quotes.append(" ".join(current))
            current = []
    if current:
        quotes.append(" ".join(current))
    return [re.sub(r"\s+", " ", q).strip() for q in quotes if q.strip()]


@traced
def deduplicate(quotes):
    """Garde la première occurrence de chaque citation ; les suivantes trop proches sont écartées."""
    kept, kept_keys = [], []
    for text in quotes:
        key = normalize(text)
        # On compare à toutes les citations déjà gardées et on retient la plus proche.
        best_ratio, best_index = max(
            ((difflib.SequenceMatcher(None, key, other).ratio(), i) for i, other in enumerate(kept_keys)),
            default=(0.0, None),
        )
        if best_ratio >= DUPLICATE_RATIO:
            log.debug(
                "Doublon écarté (%.0f %% identique à %s) : %s",
                best_ratio * 100,
                short_repr(kept[best_index]),
                short_repr(text),
            )
            continue
        kept.append(text)
        kept_keys.append(key)
    return kept


@traced
def classify(text, rules):
    """Métadonnées d'une citation, d'après les règles `rules` (IngestRules) de sa persona."""
    lower = text.lower()
    themes = [t for t, words in rules.themes.items() if any(contains_word(lower, w) for w in words)]

    words = len(text.split())
    length = "aphorisme" if words < 20 else "moyen" if words < 100 else "monologue"

    if "?" in text:
        tone = "questionnant"
    elif text.count("...") >= 2:
        tone = "contemplatif"
    else:
        tone = "affirmatif"

    contexts = [rules.contexts[t] for t in themes if t in rules.contexts]
    return {
        "themes": themes or [rules.default_theme],
        "tone": tone,
        "length": length,
        "search_contexts": contexts or [rules.default_context],
        "word_count": words,
    }


@traced
def build_citations(markdown, rules):
    """Renvoie (nombre de citations brutes, liste des citations structurées)."""
    raw = extract_quotes(markdown)
    citations = [
        {"id": f"quote_{i:03d}", "text": text, **classify(text, rules)}
        for i, text in enumerate(deduplicate(raw), start=1)
    ]
    return len(raw), citations


@traced
def run(persona):
    """citations.md de la persona -> data/<slug>/citations.json."""
    source, destination = persona.citations_md, persona.citations_json
    log.debug("Lecture de %s", source)
    raw_count, citations = build_citations(source.read_text(encoding="utf-8"), persona.ingest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(citations, ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("%d citations écrites dans %s", len(citations), destination)
    return raw_count, citations
