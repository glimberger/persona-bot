"""Configuration centralisée de persona-bot."""

import os
from pathlib import Path

# src/persona_bot/config.py -> racine du projet
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Les personas (prompt, messages, citations) : un dossier chacune, voir personas.py.
PERSONAS_DIR = PROJECT_ROOT / "personas"
# Les fichiers générés : citations structurées (data/<slug>/citations.json) et index Chroma.
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DB_PATH = DATA_DIR / "chroma"

# Modèle d'embeddings local et multilingue (384 dimensions), téléchargé au premier lancement.
# Anthropic ne fournit pas d'API d'embeddings : on vectorise en local, sans clé API.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Modèle de langage qui génère les réponses : "claude" (API d'Anthropic, payante, dans le
# cloud) ou "ollama" (modèle open source exécuté localement, gratuit). Voir llm.py.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "claude")

CLAUDE_MODEL = "claude-opus-5"
MAX_RESPONSE_TOKENS = 16000

# Adresse du serveur Ollama : la machine locale par défaut, ou une autre machine du réseau
# (par exemple le Mac, appelé depuis le Pi : http://192.168.1.20:11434).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# Modèle de 3 milliards de paramètres (Mistral), assez petit pour un Raspberry Pi 5 de 8 Go.
# Comparaison avec gemma3:4b dans le README, section "Choisir le modèle de langage".
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:3b")
# Une réponse de 60 à 120 mots tient largement en 1024 tokens. Une limite plus haute ne sert
# à rien avec un modèle local, dont la fenêtre de contexte est bien plus petite que celle de Claude.
OLLAMA_MAX_TOKENS = 1024

# Nombre d'échanges (question + réponse) gardés en mémoire par conversation.
# Au-delà, les plus anciens sont oubliés : sinon chaque appel coûterait de plus en plus cher.
# 1 = le bot se souvient seulement de l'échange précédent (pour "et l'amour ?" par exemple) ;
# 0 = aucune mémoire, chaque message est traité seul.
MAX_HISTORY_TURNS = 1

# Nombre de citations injectées dans le prompt, et similarité cosinus minimale (0 à 1).
# Avec ce modèle, une citation pertinente obtient typiquement 0.3 à 0.6.
RETRIEVE_K = 3
SIMILARITY_THRESHOLD = 0.2
