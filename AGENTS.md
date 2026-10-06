# Instructions pour les agents

Ce fichier s'adresse aux agents de code (Claude Code, Codex, Cursor…) qui travaillent sur ce
dépôt. Lis-le avant toute modification.

## Un projet pédagogique avant tout

Ce projet (persona-bot) fait parler des personas, chacune servie par son propre bot Telegram :
Jean-Claude Van Damme et Godefroy de Montmirail, qui s'appuient sur de vraies répliques ; une
persona peut aussi n'avoir qu'une description. Mais son vrai but est **d'apprendre** : comprendre le RAG (*Retrieval-Augmented
Generation*), les embeddings, les bases vectorielles, l'appel à un LLM, puis le déploiement
d'un bot Telegram sur un Raspberry Pi.

Le lecteur visé est un·e développeur·se qui connaît Python mais **ne connaît pas le RAG** ni
le machine learning. Chaque changement doit l'aider à comprendre, pas seulement fonctionner.

Conséquence : **explique toujours les fonctions et les comportements**, dans le code comme
dans tes réponses.

## Expliquer dans le code

- Chaque module commence par une docstring qui dit **quelle étape du pipeline** il
  implémente et **pourquoi elle existe** (voir `src/persona_bot/index.py` ou `bot.py`).
- Chaque fonction ou classe non triviale a une docstring ou un commentaire qui explique son
  rôle et, surtout, **le raisonnement** : pourquoi ce choix, quelle alternative on a écartée,
  quel piège on évite.
- Commente le **pourquoi**, pas le quoi. Un bon commentaire ici :
  ```python
  # Par défaut Chroma mesure une distance L2 ; on veut la distance cosinus
  # pour que "1 - distance" soit bien une similarité cosinus.
  ```
  Un mauvais : `# crée la collection`.
- Nomme les concepts quand ils apparaissent (embedding, similarité cosinus, long polling,
  injection de dépendances…) et explique-les brièvement à leur première occurrence.
- Préfère un code simple et lisible à un code astucieux : il doit pouvoir être lu par un
  débutant en RAG.

## Expliquer dans tes réponses

- Avant d'agir, dis ce que tu vas faire et pourquoi. Après, explique ce que tu as changé,
  comment ça marche et ce que ça implique.
- Quand tu fais un choix technique (librairie, modèle, architecture), présente les
  alternatives et le compromis, en termes compréhensibles pour le lecteur visé.
- Définis le jargon au lieu de le supposer connu.

## Honnêteté et exactitude

- **N'invente jamais de résultats.** Tout chiffre, score de similarité ou exemple de sortie
  cité dans la doc doit venir d'une exécution réelle du code. Une première version du projet
  contenait des exemples inventés (« similarité 0,95 ») et de faux embeddings (un hachage
  SHA-256) : le code tournait, mais la recherche renvoyait des citations au hasard.
- Si tu n'as pas pu tester quelque chose (clé API absente, matériel indisponible), dis-le
  explicitement.
- Signale les limites et les pièges plutôt que de les cacher : ils font partie de ce qu'on
  apprend (voir la section « Limites et pièges » de `docs/GUIDE_RAG.md`).

## Garder la documentation à jour

La documentation fait partie du livrable. Toute modification du code doit être répercutée
dans :

- `README.md` : référence (installation, commandes, étapes, structure) ;
- `docs/GUIDE_RAG.md` : le guide qui explique le RAG depuis zéro, avec des exemples réels ;
- `docs/DEPLOIEMENT_PI.md` : l'installation sur un Raspberry Pi (tout ce qui touche au
  déploiement, au service `deploy/persona-bot.service` ou aux dépendances sous Linux) ;
- `.env.example` : toute nouvelle variable d'environnement, avec un commentaire.

Une information n'est écrite qu'à **un seul endroit** : le README donne le pratique
(commandes, réglages, procédures), le guide donne les explications (le pourquoi). L'autre
document y renvoie par un lien vers la section (`[guide, section 4](docs/GUIDE_RAG.md#...)`),
au lieu de répéter. Vérifie que les ancres des liens existent.

Si un chiffre change (nombre de citations, scores, dimensions…), mets-le à jour partout.
Vérifie qu'aucune référence obsolète ne subsiste (anciens chemins, anciennes commandes).

La documentation est rédigée en **français**, en **tutoyant** le lecteur.

## Repères techniques

```
personas/<slug>/persona.toml   nom, prompt système, messages        (obligatoire)
personas/<slug>/citations.md   → persona ingest → data/<slug>/citations.json
                               → persona index  → data/chroma/ (collection citations_<slug>)
                                 persona search / eval <slug>       (seulement avec citations)
persona chat / ask <slug>, persona telegram (un bot par TELEGRAM_TOKEN_<SLUG>)
```

- Une persona **sans** `citations.md` doit continuer de fonctionner partout (pas de RAG, pas de
  chargement de Chroma). Garde cette propriété et teste-la.
- Rien de propre à une persona dans le code : textes, prompts et mots-clés vont dans son
  `persona.toml`.
- Le code est un package Python dans `src/persona_bot/`, géré par **uv**.
- Commandes :
  ```bash
  uv run persona --help        # toutes les commandes du projet
  uv run pytest                # tests (quelques secondes, sans clé API ni modèle)
  uv run ruff check .          # lint
  uv run ruff format .         # formatage
  ```
- Après toute modification de code : lance les tests et ruff, et vérifie le comportement
  réel quand c'est possible (par exemple `uv run persona search jcvd "..."`).
- **Logs** : décore chaque nouvelle fonction du projet avec `@traced` (`persona_bot.logs`) et
  ajoute des `log.debug(...)` pour les actions internes importantes, afin que
  `persona --debug` montre tout ce qui se passe. **Jamais** `@traced` sur une fonction qui reçoit
  un secret en argument (token, clé API) : ses arguments seraient écrits dans les logs.
  Le masquage automatique de `short_repr` (formats de token Telegram et de clé Anthropic)
  n'est qu'une seconde ligne de défense ; ajoute-y tout nouveau format de secret.
- Les tests n'appellent jamais la vraie API Claude, ni un vrai serveur Ollama, ni le modèle d'embeddings : ils utilisent
  de faux objets injectés (`PersonaBot(persona, retriever=..., client=...)`) et la persona de
  test de `tests/conftest.py`. Garde cette propriété.
- Les secrets (`ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN_<SLUG>`) vivent uniquement dans `.env`,
  jamais dans le code ni dans la doc.
- Après une modification d'un `personas/<slug>/citations.md` ou de l'ingestion, relance
  `uv run persona ingest && uv run persona index`.
- Toute modification qui touche la recherche (ingestion, embeddings, index, retriever) se
  juge avec `uv run persona eval`, avant et après. Rapporte les deux scores. N'adapte jamais la
  méthode ou le jeu d'évaluation (`personas/<slug>/eval_search.json`) pour faire monter le score : ajoute
  plutôt de nouvelles questions réalistes, et vérifie que leurs fragments sont uniques.
