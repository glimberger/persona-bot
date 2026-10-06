"""
Outils partagés par les tests (pytest charge ce fichier automatiquement).

Les tests utilisent une persona fabriquée ici plutôt que celles de personas/ : ils vérifient
le mécanisme (le bon message envoyé au bon moment), pas le texte d'une persona réelle, qui
peut changer sans que le code soit faux.
"""

import pytest

from persona_bot.personas import REQUIRED_MESSAGES, Persona


def make_persona(directory, slug="test"):
    """Une persona minimale. Elle a des citations seulement si `directory/citations.md` existe."""
    return Persona(
        slug=slug,
        name="Testeur",
        system_prompt="Tu es un personnage de test.",
        # "message welcome", "message reset"... : faciles à reconnaître dans les assertions.
        messages={name: f"message {name}" for name in REQUIRED_MESSAGES},
        directory=directory,
    )


@pytest.fixture
def persona(tmp_path):
    """Persona de test sans citations (son dossier, temporaire, est vide)."""
    return make_persona(tmp_path)
