"""
Les personas : qui parle, et avec quelles sources.

Une persona est un personnage que le modèle de langage incarne. Tout ce qui lui est propre
vit dans un dossier `personas/<slug>/`, hors du code :
  - persona.toml      : son nom, son prompt système, ses messages (accueil, erreurs...) ;
  - citations.md      : facultatif. S'il existe, la persona utilise le RAG (ses citations sont
                        indexées et injectées dans chaque requête) ; sinon, le modèle ne
                        s'appuie que sur le prompt système ;
  - eval_search.json  : facultatif, le jeu d'évaluation de sa recherche (`persona eval`).

Le "slug" est l'identifiant court de la persona (le nom du dossier, par exemple "jcvd").
On le retrouve dans les commandes (`persona chat jcvd`), dans le nom de sa collection Chroma
et dans la variable du token Telegram (TELEGRAM_TOKEN_JCVD).

Pourquoi des fichiers plutôt que du code ? Ajouter une persona revient alors à écrire du texte,
sans toucher au programme. Et le même code sert toutes les personas : ce qui marche pour l'une
marche pour les autres.
"""

import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from persona_bot.config import DATA_DIR, PERSONAS_DIR
from persona_bot.logs import traced

log = logging.getLogger(__name__)

# Phrases que le programme envoie lui-même (sans le modèle) : toutes sont obligatoires, pour
# qu'une persona incomplète soit signalée au démarrage plutôt qu'au milieu d'une conversation.
REQUIRED_MESSAGES = ("welcome", "reset", "refusal", "rate_limit", "api_error", "connection_error", "farewell")

# Le slug sert aussi de nom de variable d'environnement (TELEGRAM_TOKEN_<SLUG>), où les tirets
# sont interdits : on se limite aux minuscules, chiffres et "_".
SLUG_PATTERN = re.compile(r"[a-z0-9_]+")


class PersonaError(Exception):
    """Persona introuvable, mal décrite ou pas indexée : le message dit quoi corriger."""


@dataclass(frozen=True)
class IngestRules:
    """
    Règles de l'étape 1 (ingest.py) pour ajouter des métadonnées aux citations.

    Elles dépendent du vocabulaire de chaque persona (JCVD parle d'"awareness", une autre
    persona non) : elles sont donc dans persona.toml, section [ingest], et non dans le code.
    """

    themes: dict = field(default_factory=dict)  # thème -> mots-clés qui le signalent
    contexts: dict = field(default_factory=dict)  # thème -> situation où la citation est utile
    default_theme: str = "général"
    default_context: str = "général"


# frozen=True : une persona ne change pas une fois chargée. Plusieurs bots peuvent la lire en
# même temps (un par conversation Telegram) sans risque que l'un la modifie sous les pieds
# des autres.
@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    system_prompt: str
    messages: dict
    directory: Path
    ingest: IngestRules = field(default_factory=IngestRules)

    # Les chemins se déduisent du slug : rien à configurer, et pas de risque que deux personas
    # partagent par erreur le même fichier ou la même collection.
    @property
    def citations_md(self):
        return self.directory / "citations.md"

    @property
    def has_citations(self):
        """Vrai si la persona a des citations, donc utilise le RAG."""
        return self.citations_md.exists()

    @property
    def eval_json(self):
        return self.directory / "eval_search.json"

    @property
    def citations_json(self):
        # Fichier généré par `persona ingest` : il va dans data/, avec les autres fichiers générés.
        return DATA_DIR / self.slug / "citations.json"

    @property
    def collection_name(self):
        # Une collection Chroma par persona, dans la même base : la recherche d'une persona ne
        # peut jamais renvoyer les citations d'une autre.
        return f"citations_{self.slug}"


@traced
def list_personas(personas_dir=PERSONAS_DIR):
    """Slugs des personas disponibles : les sous-dossiers qui contiennent un persona.toml."""
    return sorted(p.parent.name for p in personas_dir.glob("*/persona.toml"))


@traced
def load_persona(slug, personas_dir=PERSONAS_DIR):
    if not SLUG_PATTERN.fullmatch(slug):
        raise PersonaError(f"Slug {slug!r} invalide : minuscules, chiffres et _ uniquement.")
    directory = personas_dir / slug
    path = directory / "persona.toml"
    if not path.exists():
        available = ", ".join(list_personas(personas_dir)) or "aucune"
        raise PersonaError(f"Persona {slug!r} introuvable ({path}). Personas disponibles : {available}.")

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        # L'erreur de tomllib donne la ligne et la colonne : on la garde telle quelle.
        raise PersonaError(f"{path} : TOML invalide ({error})") from error

    missing = [name for name in ("name", "system_prompt") if not data.get(name)]
    messages = data.get("messages", {})
    missing += [f"messages.{name}" for name in REQUIRED_MESSAGES if not messages.get(name)]
    if missing:
        raise PersonaError(f"{path} : champ(s) manquant(s) : {', '.join(missing)}")

    try:
        ingest = IngestRules(**data.get("ingest", {}))
    except TypeError as error:  # clé inconnue dans [ingest], souvent une faute de frappe
        raise PersonaError(f"{path} : section [ingest] invalide ({error})") from error

    persona = Persona(
        slug=slug,
        name=data["name"],
        system_prompt=data["system_prompt"],
        messages=messages,
        directory=directory,
        ingest=ingest,
    )
    log.debug(
        "Persona %s chargée : %s, prompt de %d caractères, %s",
        slug,
        persona.name,
        len(persona.system_prompt),
        "avec citations (RAG)" if persona.has_citations else "sans citations (pas de RAG)",
    )
    return persona
