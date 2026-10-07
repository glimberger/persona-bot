# persona-bot — des personas sur Telegram, un RAG pédagogique

Des bots conversationnels qui incarnent chacun un personnage, une **persona**, et qu'on
retrouve sur Telegram : Jean-Claude Van Damme, Godefroy de Montmirail et Jacquouille la
Fripouille, les deux derniers venant des *Visiteurs*. Toutes trois s'appuient sur de vraies
répliques, mais une persona peut aussi n'avoir qu'une description. Le projet sert à comprendre, pas à pas, le
pattern **RAG** (*Retrieval-Augmented Generation*) : chercher des passages pertinents dans une
base de textes, puis les donner à un LLM pour qu'il s'en inspire. Et à voir ce qui change
quand on s'en passe.

Le projet s'appelait « JCVD Bot » quand il n'avait qu'une persona. Tu as une installation de
cette époque ? Voir [Migrer depuis JCVD Bot](#migrer-depuis-jcvd-bot).

**Tu ne connais pas le RAG ?** Commence par [docs/GUIDE_RAG.md](docs/GUIDE_RAG.md) : il explique les
concepts depuis zéro, avec des exemples tirés de ce projet. Ce README sert ensuite de référence.

## Installation

```bash
brew install uv          # ou : curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync                  # crée .venv/, installe les dépendances et la commande `persona`
export ANTHROPIC_API_KEY="sk-ant-..."   # à partir de l'étape 3b, sauf avec Ollama (voir plus bas)
```

`uv run <commande>` exécute une commande dans l'environnement du projet, sans avoir à
l'activer (`source .venv/bin/activate` reste possible si tu préfères taper `persona` directement).

Pourquoi un environnement virtuel (`.venv/`) ? Pour que les versions des librairies de ce
projet n'entrent pas en conflit avec celles d'autres projets Python de ta machine.

Au premier lancement, le modèle d'embeddings (quelques centaines de Mo) est téléchargé automatiquement.

### Option : avec Nix

Si tu utilises [Nix](https://nixos.org), le dépôt fournit un environnement de développement
(`flake.nix`) avec Python et uv, aux versions figées dans `flake.lock` : rien à installer avec
Homebrew.

```bash
nix develop              # ouvre un shell avec Python et uv
uv sync                  # puis comme ci-dessus
```

Avec [direnv](https://direnv.net), ce shell s'active tout seul quand tu entres dans le dossier
(`.envrc` contient `use flake`) : lance `direnv allow` une fois.

Sur Mac, dans ce shell, uv crée `.venv` avec le Python fourni par Nix. Un `.venv` lié à un Python
installé ailleurs casse quand ce Python disparaît (par exemple désinstallé de Homebrew) ; uv le
recrée alors tout seul au prochain `uv run`. Sur Linux, le shell laisse au contraire uv
utiliser son propre Python : avec celui de Nix, numpy ne s'importe pas
([pourquoi](docs/DEPLOIEMENT_PI.md#le-piège-du-python-de-nix)). Les dépendances Python restent
gérées par uv (`pyproject.toml`, `uv.lock`), avec ou sans Nix.

## Les personas

Une persona est un dossier de `personas/`, dont le nom est son **slug** : l'identifiant court
qu'on donne aux commandes (`persona chat jcvd`). `uv run persona list` les affiche.

```
personas/jcvd/
├── persona.toml        obligatoire : nom, prompt système, messages
├── citations.md        facultatif : ses citations. Présent = la persona utilise le RAG
└── eval_search.json    facultatif : jeu d'évaluation de sa recherche (`persona eval`)
```

Le slug ne contient que des minuscules, des chiffres et `_` : il sert aussi à nommer la
variable de son token Telegram (`TELEGRAM_TOKEN_JCVD`), où les tirets sont interdits.

**`persona.toml`** est un fichier [TOML](https://toml.io/fr/) (des paires `clé = valeur`
regroupées en sections). Il contient :

| Clé | Rôle |
|---|---|
| `name` | Nom affiché dans le terminal (`Jean-Claude`) |
| `system_prompt` | Le prompt système : qui est la persona, comment elle parle, le format des réponses |
| `[messages]` | Les phrases que le programme envoie lui-même, sans le modèle : `welcome` (`/start`), `reset` (`/reset`), `refusal` (le modèle refuse de répondre), `rate_limit`, `api_error`, `connection_error` (erreurs du modèle de langage), `farewell` (fin de `persona chat`). Toutes sont obligatoires |
| `[ingest]` | Facultatif, utile seulement avec des citations : les mots-clés qui donnent un thème à chaque citation (étape 1) |

`personas/jcvd/persona.toml` sert d'exemple commenté. Une persona incomplète est signalée
dès son chargement, avec la liste des champs manquants.

**Ajouter une persona**

1. Crée `personas/<slug>/persona.toml` (copie celui de JCVD et adapte-le). Écris un
   `system_prompt` qui ne parle **pas** de citations si ta persona n'en a pas.
2. Essaie-la dans le terminal : `uv run --env-file .env persona chat <slug>`.
3. Si elle a des citations : mets-les dans `personas/<slug>/citations.md` (un bloc
   commençant par `>` par citation) et lance `uv run persona ingest <slug>` puis
   `uv run persona index <slug>`. Son prompt système doit alors expliquer au modèle les
   balises `<citations>` qu'il recevra (voir celui de JCVD).
4. Pour Telegram : crée-lui un bot avec @BotFather et ajoute `TELEGRAM_TOKEN_<SLUG>` dans
   `.env` (voir [l'étape 4](#étape-4--brancher-les-personas-sur-telegram-persona-telegram-telegram_apppy)).

Avec ou sans citations, quelle différence dans les réponses, et quand préférer l'un ou
l'autre : [guide, section 10](docs/GUIDE_RAG.md#10-une-persona-sans-citations--quand-le-rag-nest-pas-là).

## Les étapes

Tout passe par une seule commande, `persona` (`uv run persona --help` pour l'aide). Les
commandes prennent le slug de la persona :

```bash
uv run persona list                              # les personas disponibles
uv run persona ingest jcvd                       # 1.  Markdown → JSON structuré
uv run persona index jcvd                        # 2.  JSON → index vectoriel Chroma
uv run persona search jcvd "J'ai peur d'échouer" # 3a. voir les citations trouvées (sans clé API)
uv run persona eval jcvd                         # 3a. mesurer la qualité de la recherche
uv run persona ask jcvd "J'ai peur d'échouer"    # 3b. une réponse, avec des mesures
uv run persona chat jcvd                         # 3b. discuter avec la persona dans le terminal
uv run --env-file .env persona telegram          # 4.  un bot Telegram par persona
```

Les étapes 1 à 3a ne concernent que les personas qui ont des citations. Sans slug,
`ingest`, `index` et `eval` traitent toutes celles qui en ont. Les étapes 1 et 2 sont à
relancer seulement quand le fichier `citations.md` d'une persona change.

### Étape 1 — Structurer les données (`persona ingest`, `ingest.py`)

Lit `personas/jcvd/citations.md` (89 blocs commençant par `>`), supprime les 17 doublons ou
quasi-doublons et écrit `data/jcvd/citations.json` : 72 citations uniques, avec des
métadonnées calculées par mots-clés (`themes`, `tone`, `length`, `search_contexts`). Les
mots-clés des thèmes viennent de la section `[ingest]` de son `persona.toml`.

Comment les doublons sont détectés, et pourquoi ces métadonnées ne servent pas à la
recherche : [guide, section 8](docs/GUIDE_RAG.md#8-limites-et-pièges).

### Étape 2 — Vectoriser et indexer (`persona index`, `index.py`)

Transforme chaque citation en vecteur avec le modèle local
`paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, sans clé API) et enregistre le tout
dans Chroma, dans `data/chroma/`, avec la distance cosinus. Chaque persona a sa propre
**collection** (l'équivalent d'une table) : `citations_jcvd` pour JCVD. La recherche d'une
persona ne peut donc jamais renvoyer les citations d'une autre.

Ce qu'est un embedding, pourquoi ce modèle et pourquoi le cosinus plutôt que la distance
euclidienne : [guide, section 4](docs/GUIDE_RAG.md#4-les-embeddings--transformer-du-sens-en-nombres) et
[section 5](docs/GUIDE_RAG.md#5-la-base-vectorielle--retrouver-les-voisins-rapidement).

### Étape 3a — Retrouver les citations (`persona search`, `persona eval`, `retriever.py`, `evaluation.py`)

`persona search jcvd "question"` affiche les citations les plus proches et leur similarité. Exemple réel :

```
🔍 "Comment devenir meilleur ?"
   0.487  Ma devise, c'est toujours : se recréer. Il faut se recréer... pour recréer... a better you
   0.436  Ma devise, c'est : il faut se recréer, pour recréer !
   0.395  Mon modèle, c'est moi-même ! Je suis mon meilleur modèle parce que je connais mes erreurs...
```

Comment lire ces scores, et le rôle du seuil `SIMILARITY_THRESHOLD` (0,2 dans `config.py`) :
[guide, section 4](docs/GUIDE_RAG.md#comparer-deux-vecteurs--la-similarité-cosinus) et
[section 8](docs/GUIDE_RAG.md#8-limites-et-pièges).

`persona eval jcvd` rejoue les 30 questions de `personas/jcvd/eval_search.json` et affiche, pour chacune, le
rang de la bonne citation, puis les scores hit@3 et MRR. Lance-le avant et après toute
modification de la recherche. Ce que mesurent ces indicateurs, les scores actuels et
l'expérience qu'ils ont permis d'écarter : [guide, section 9](docs/GUIDE_RAG.md#9-mesurer-avant-daméliorer).

### Étape 3b — Générer la réponse (`persona chat`, `persona ask`, `bot.py`, `llm.py`)

À chaque message, `PersonaBot` récupère les 3 citations les plus proches, les ajoute au
message envoyé au modèle de langage et lui demande de répondre dans le style de la persona,
décrit par son prompt système. Pour une persona sans citations, la recherche est sautée et le
message part tel quel. Le détail (prompt système, historique, appel au modèle) :
[guide, section 7](docs/GUIDE_RAG.md#7-parcours-complet-dun-message-dans-le-code).

`persona ask jcvd "question"` donne une seule réponse suivie de mesures : nombre de mots (cible du
prompt : 60 à 120), de phrases, question finale ou non, durée, tokens. Pratique pour vérifier
qu'un changement de prompt ou de modèle a l'effet voulu.

### Choisir le modèle de langage : Claude ou Ollama

La variable `LLM_BACKEND` choisit le modèle qui écrit les réponses ; la recherche des
citations, elle, ne change pas ([guide, section 7.3](docs/GUIDE_RAG.md#73-generation--lappel-au-modèle-de-langage)) :

| | `LLM_BACKEND=claude` (défaut) | `LLM_BACKEND=ollama` |
|---|---|---|
| Où tourne le modèle | Serveurs d'Anthropic | Ta machine (ou une machine de ton réseau) |
| Coût | Payant, à l'usage | Gratuit (hors électricité) |
| Confidentialité | Les messages partent chez Anthropic | Rien ne sort de chez toi (Telegram voit toujours les messages) |
| Qualité | Suit finement le prompt | Nettement moins fidèle au prompt (voir mesures) |
| Clé API | `ANTHROPIC_API_KEY` | Aucune |

**Comment ça marche** (`src/persona_bot/llm.py`) : Ollama expose une API compatible avec celle
d'Anthropic. Le même client Python sert donc aux deux ; avec Ollama, on change seulement son
adresse (`OLLAMA_BASE_URL`) et on lui donne une clé factice. Les paramètres propres à Claude
(`effort` et `fallbacks`, expliqués dans le [guide, section 7.3](docs/GUIDE_RAG.md#73-generation--lappel-au-modèle-de-langage))
ne sont pas envoyés à Ollama.

**Mise en route avec Ollama**

1. Installe Ollama (<https://ollama.com>) et télécharge un modèle :
   ```bash
   ollama pull ministral-3:3b
   ```
2. Dans `.env` : `LLM_BACKEND=ollama` (et, si besoin, `OLLAMA_MODEL`, `OLLAMA_BASE_URL`).
3. Vérifie : `uv run --env-file .env persona ask jcvd "J'ai peur d'échouer"`.

**La fenêtre de contexte, un piège silencieux.** Un modèle local ne lit qu'une quantité
limitée de texte à la fois (sa fenêtre de contexte, réglée par Ollama). Si la conversation la
dépasse, Ollama coupe le début **sans erreur**, et le bot perd son prompt système, donc sa
personnalité. Mesures réelles avec `ministral-3:3b` :

- premier message : environ 900 tokens (prompt système + citations + question) ;
- messages suivants : le bot ne gardant que le dernier échange (`MAX_HISTORY_TURNS = 1`),
  le total reste entre **1 100 et 1 500 tokens**.

Une fenêtre de **4 096 tokens** suffit donc largement, 8 192 laisse de la marge (c'est la
valeur utilisée sur le Mac de développement). Si tu augmentes `MAX_HISTORY_TURNS`, refais la
mesure : avec 10 échanges, le total montait à 4 000–4 400 tokens et dépassait une fenêtre de
4 096. Vérifie la fenêtre dans la colonne `CONTEXT` de `ollama ps` (pendant qu'un modèle est
chargé). Pour l'agrandir, lance le serveur avec `OLLAMA_CONTEXT_LENGTH=8192 ollama serve`
(ou règle-la dans les paramètres de l'application Ollama). Pour suivre le nombre de tokens lus
à chaque message, utilise `persona --debug` ou `persona ask`.

Attention à la lecture des tokens : Ollama, comme Claude, garde en cache le début d'une
requête déjà lue. `input_tokens` ne compte alors que la partie nouvelle ; le total lu est la
somme avec `cache_read_input_tokens` (fonction `total_input_tokens` dans `llm.py`).

**Mesures réelles**, 5 mêmes questions, chacune dans une conversation neuve, avec le prompt
système actuel. Les modèles Ollama tournent sur un Mac M5 (24 Go), Claude sur les serveurs
d'Anthropic :

| Modèle | Taille | Durée par réponse | Mots (cible 60–120) | Phrases (cible 2–3) | Observations |
|---|---|---|---|---|---|
| `claude-opus-5` | — | 4,9 à 6,5 s | 101 à 110 | 2 à 3 | Respecte le budget, les longues phrases, le texte brut ; « tu comprends ? » accroché en fin de phrase (2 réponses sur 5) ; citations fondues dans le discours |
| `ministral-3:3b` | 3,0 Go | 4,8 à 8,1 s | 131 à 214 | 8 à 14 | Bon français, reformule les citations ; ajoute des didascalies en `*italique*` (« *soupir profond* »), dépasse le budget de mots |
| `gemma3:4b` | 3,3 Go | 5,0 à 6,3 s | 116 à 165 | 11 à 22 | Recopie des citations entières, tics répétés (« c'est… c'est », « Tu comprends ? » en ouverture) |

Les petits modèles locaux ne respectent vraiment ni la longueur, ni le nombre de phrases, ni
la mise en forme : c'est le prix d'un modèle de 3 à 4 milliards de paramètres. Côté coût, une
réponse de Claude lit environ 1 400 à 2 000 tokens et en écrit environ 250, soit de l'ordre de
1,5 centime de dollar par message (au tarif de `claude-opus-5` en septembre 2026 : 5 $ par
million de tokens lus, 25 $ par million écrits). Les tokenizers diffèrent d'un modèle à
l'autre : ne compare pas directement le nombre de tokens de Claude et d'Ollama.

`ministral-3:3b` est le modèle Ollama par défaut. Les deux modèles Ollama tiennent dans un
Raspberry Pi 5 de 8 Go, mais y sont lents : de 48 à 107 s par réponse, contre 4,8 à 8,1 s sur
le Mac ([mesures sur le Pi](docs/DEPLOIEMENT_PI.md#13-ollama-sur-le-pi)).

**Ollama sur une autre machine.** Le bot peut tourner sur le Pi et appeler un Ollama installé
sur le Mac : `OLLAMA_BASE_URL=http://<adresse-du-mac>:11434`. Ollama n'écoute par défaut que
sur la machine locale : sur le Mac, il faut le lancer avec `OLLAMA_HOST=0.0.0.0` pour qu'il
accepte les connexions du réseau.

### Étape 4 — Brancher les personas sur Telegram (`persona telegram`, `telegram_app.py`)

`telegram_app.py` n'est qu'un **adaptateur** : il reçoit les messages Telegram, les passe au
même `PersonaBot` que le chat du terminal, et renvoie la réponse. Toute la logique RAG reste
dans `bot.py`.

**Un bot Telegram par persona.** Chaque persona a son propre bot, créé avec @BotFather :
dans Telegram, elle apparaît comme un contact à part, avec son nom, sa photo et sa propre
conversation. `persona telegram` lance tous les bots dont le token est dans `.env`, dans un
seul programme. Une persona sans token est simplement ignorée : tu peux l'essayer dans le
terminal avant de lui créer un bot.

**Mise en route**

1. Sur Telegram, écris à **@BotFather**, envoie `/newbot` et suis les instructions. Il te
   donne un **token** : c'est le mot de passe de ce bot, ne le partage pas. Recommence pour
   chaque persona (`/setuserpic` dans @BotFather pour lui donner une photo).
2. Copie le fichier d'exemple et remplis `ANTHROPIC_API_KEY` et un `TELEGRAM_TOKEN_<SLUG>`
   par persona (`TELEGRAM_TOKEN_JCVD` pour JCVD, `TELEGRAM_TOKEN_GODEFROY` pour Godefroy,
   `TELEGRAM_TOKEN_JACQUOUILLE` pour Jacquouille) :
   ```bash
   cp .env.example .env
   chmod 600 .env        # lisible par toi seul
   ```
3. Lance les bots :
   ```bash
   uv run --env-file .env persona telegram
   ```
   Une ligne par bot confirme son démarrage : `Bot @…_bot démarré (persona jcvd)`.
4. Autorise-toi en suivant la procédure ci-dessous : tant que la liste est vide, les bots
   refusent tout le monde.

**Autoriser une personne (toi compris)**

La liste `TELEGRAM_ALLOWED_USERS` est commune à tous les bots : une personne autorisée peut
parler à toutes les personas.

1. Les bots tournent. La personne cherche l'un d'eux sur Telegram (par son nom `@…_bot`) et
   lui envoie n'importe quel message. Le bot ne lui répond pas.
2. Dans le terminal où tournent les bots, une ligne affiche son identifiant :
   ```
   WARNING persona_bot.telegram_app Accès refusé à Marie Dupont (id 987654321)
   ```
3. Ajoute cet identifiant dans `TELEGRAM_ALLOWED_USERS` du fichier `.env`, séparé des autres
   par une virgule :
   ```
   TELEGRAM_ALLOWED_USERS=123456789,987654321
   ```
4. Arrête les bots (Ctrl+C) et relance-les : la liste n'est lue qu'au démarrage.

L'identifiant est un nombre fixe attribué par Telegram. Ce n'est pas le nom d'utilisateur
(`@marie`), que la personne peut changer à tout moment : c'est pour ça que la liste utilise
les identifiants. La personne peut aussi obtenir le sien auprès d'un bot tiers comme
@userinfobot, mais passer par ton propre bot évite de dépendre d'un service extérieur.

Pour retirer l'accès à quelqu'un : enlève son identifiant de la liste et relance les bots.

`uv run --env-file .env` charge les variables du fichier `.env` avant de lancer le script.
Le fichier `.env` est ignoré par git : les secrets ne doivent jamais se retrouver dans le code.

`HF_HUB_OFFLINE=1` (dans `.env`) empêche le bot de contacter le site Hugging Face à chaque
démarrage. Le modèle doit donc déjà être téléchargé : lance l'étape 2 avant (sans `.env`).

**Commandes dans Telegram** : `/start` pour la présentation, `/reset` pour effacer
l'historique de ta conversation avec cette persona. Les textes de ces réponses, comme ceux des
messages d'erreur, viennent de la section `[messages]` de son `persona.toml`.

**« Une autre instance du bot tourne déjà avec le même token »** : Telegram n'accepte qu'un
seul programme à la fois pour lire les messages d'un bot. Ce message apparaît si tu lances
les bots deux fois (deux terminaux, ou le Mac et le Pi en même temps). Arrête l'une des deux
instances. Pour la même raison, deux personas ne peuvent pas partager un token :
`persona telegram` refuse de démarrer si c'est le cas. Les autres erreurs de communication avec Telegram passent par le même
gestionnaire (`on_error` dans `telegram_app.py`) : une coupure réseau est signalée en une
ligne, la librairie réessayant d'elle-même.

**Points de conception**

- **Long polling** : le bot demande sans arrêt à Telegram s'il a de nouveaux messages. Il ne
  fait que des connexions sortantes : aucun port à ouvrir, il marche derrière n'importe quelle box.
- **Liste blanche** (`TELEGRAM_ALLOWED_USERS`) : sans elle, n'importe qui trouvant ton bot
  dépenserait tes crédits API.
- **Un historique par conversation** : chaque personne a le sien avec chaque persona, et ne
  voit jamais celui des autres. Sa longueur est fixée par `MAX_HISTORY_TURNS` dans `config.py`, actuellement
  1 : le bot se souvient seulement de l'échange précédent (effet sur la taille des requêtes :
  voir « La fenêtre de contexte » ci-dessus).
- **Pas de blocage** : la librairie Telegram est asynchrone, mais la recherche et l'appel au
  modèle de langage sont bloquants (plusieurs secondes). On les lance dans un thread
  (`asyncio.to_thread`) pour ne pas figer le bot pendant ce temps.
- **Indicateur « en train d'écrire… »** : Telegram l'efface au bout d'environ 5 s. Le bot le
  renvoie donc toutes les 4 s tant que la réponse n'est pas prête (`keep_typing`), ce qui
  compte avec Ollama sur le Pi, où une réponse prend environ une minute.
- **Messages traités un par un** (réglage par défaut de la librairie) : deux messages
  envoyés coup sur coup au même bot ne peuvent pas se mélanger dans l'historique.
- **Plusieurs bots, un seul programme** : `app.run_polling()`, la méthode habituelle de la
  librairie, ne sait faire tourner qu'un bot, car elle garde la main jusqu'à l'arrêt.
  `run_all` refait donc à la main ses étapes de démarrage et d'arrêt pour chaque bot. Un seul
  programme plutôt qu'un par persona, pour que le modèle d'embeddings (le plus gros
  consommateur de mémoire) ne soit chargé qu'une fois, ce qui compte sur un Raspberry Pi.
- **Chiffrement** : les conversations avec un bot Telegram ne sont pas chiffrées de bout en
  bout ; Telegram voit les messages. Où part ensuite le texte : ligne « Confidentialité » du
  tableau « Choisir le modèle de langage » ci-dessus.

## Déployer sur un Raspberry Pi

Pour que les bots Telegram tournent en permanence, installe-les sur un Raspberry Pi et
confie-les à **systemd**, le gestionnaire de services de Linux : il les démarre avec le Pi et les relance
s'ils plantent. La procédure complète (carte SD, clé SSH, installation, secrets, service, mise à
jour) et les mesures relevées sur un Pi 5 sont dans
[docs/DEPLOIEMENT_PI.md](docs/DEPLOIEMENT_PI.md) ; les commandes pour gérer le service et lire
ses logs, dans sa [section 9](docs/DEPLOIEMENT_PI.md#9-installer-et-gérer-le-service). Si ton
Pi est géré avec Nix et home-manager, le service s'installe avec un module : voir la
[section 12](docs/DEPLOIEMENT_PI.md#12-variante-avec-nix-et-home-manager).

## Mode debug

Pour voir tout ce que fait le bot, ajoute `--debug` **avant** la commande :

```bash
uv run persona --debug search jcvd "J'ai peur d'échouer"
uv run persona --debug chat jcvd
uv run --env-file .env persona --debug telegram
```

Ou mets `PERSONA_DEBUG=1` dans `.env` (pratique pour les bots Telegram et, plus tard, sur le Pi).

Extrait réel de `persona --debug search jcvd "J'ai peur d'échouer" -k 4` :

```
DEBUG   persona_bot.index: ← embedding_function = <...SentenceTransformerEmbeddingFunction...> (3096 ms)
DEBUG   persona_bot.retriever: Collection 'citations_jcvd' ouverte : 72 citations
DEBUG   persona_bot.retriever: → Retriever.search(query="J'ai peur d'échouer", k=4)
DEBUG   persona_bot.retriever:   retenue  0.393   quote_035 "Le grand combat, c'est contre soi-même. [...]"
DEBUG   persona_bot.retriever:   retenue  0.352   quote_064 "Me montrer nu de dos ne me pose pas de problème [...]"
DEBUG   persona_bot.retriever: ← Retriever.search = [...] (116 ms)
```

On y lit que charger le modèle d'embeddings prend 3,1 s, alors qu'une recherche prend
0,1 s, et on voit le score de chaque citation candidate.

**Comment c'est construit** (`src/persona_bot/logs.py`) :

- Le **décorateur `@traced`**, placé sur les fonctions du projet, journalise
  automatiquement chaque appel : `→` à l'entrée avec les arguments, `←` à la sortie avec le
  résultat et la durée, `✗` si une exception est levée. Les valeurs longues sont tronquées.
  Hors mode debug, il appelle simplement la fonction, sans coût notable.
- Des **`log.debug(...)` dans le code** détaillent ce que le décorateur ne voit pas de
  l'extérieur : chaque doublon écarté pendant l'ingestion (avec son pourcentage de
  ressemblance), chaque citation retenue ou écartée par le seuil, le message exact envoyé au
  modèle de langage, le modèle qui a répondu, les tokens consommés, les messages oubliés quand
  l'historique est trop long.
- Seuls les logs du projet (`persona_bot.*`) passent en debug. Les librairies tierces restent
  silencieuses : leurs logs noieraient les nôtres, et la librairie réseau `httpx` écrirait
  le token Telegram (il fait partie des URL qu'elle journalise).
- **Les secrets sont masqués** dans tout ce que `@traced` écrit : un texte au format d'un
  token Telegram (`123456789:AAH…`) ou d'une clé Anthropic (`sk-ant-…`) devient `***`.
  C'est nécessaire : l'objet `Bot` de Telegram affiche son token quand on l'imprime
  (`ExtBot[token=…]`), et un argument qui le contient l'aurait écrit dans les logs.

**Attention à la vie privée** : en mode debug, les logs contiennent le texte des messages et
le nom des personnes qui écrivent aux bots. Active-le pour comprendre ou dépanner, pas en
permanence.

## Structure

```
persona-bot/
├── pyproject.toml / uv.lock     dépendances et commande `persona` (gérées par uv)
├── flake.nix / flake.lock       environnement de développement Nix (optionnel : Python + uv)
├── .envrc                       active cet environnement avec direnv
├── .talismanrc                  exceptions du hook Talisman (faux positifs connus)
├── .env.example                 modèle du fichier de secrets (.env, non versionné)
├── LICENSE                      licence MIT
├── personas/                    une persona par dossier (voir « Les personas »)
│   ├── jcvd/
│   │   ├── persona.toml         nom, prompt système, messages, mots-clés des thèmes
│   │   ├── citations.md         ses citations, source brute (à éditer)
│   │   └── eval_search.json     jeu d'évaluation de sa recherche (`persona eval`)
│   └── godefroy/                persona.toml et citations.md (pas encore de jeu d'évaluation)
├── data/                        fichiers générés
│   ├── <slug>/citations.json    généré par `persona ingest`, un dossier par persona
│   └── chroma/                  index vectoriel, généré par `persona index` (non versionné)
├── deploy/
│   ├── persona-bot.service      service systemd pour faire tourner les bots sur un Pi
│   └── persona-bot.nix          le même service, en module home-manager (Pi géré avec Nix)
├── docs/
│   ├── GUIDE_RAG.md             comprendre le RAG depuis zéro
│   └── DEPLOIEMENT_PI.md        installer les bots sur un Raspberry Pi
├── src/persona_bot/             le code (un package Python)
│   ├── config.py                réglages : modèles, chemins, k, seuil
│   ├── personas.py              lecture des personas (persona.toml)
│   ├── ingest.py                étape 1
│   ├── index.py                 étape 2
│   ├── retriever.py             étape 3a
│   ├── evaluation.py            étape 3a, mesure de la qualité de la recherche
│   ├── bot.py                   étape 3b, le cœur du bot
│   ├── llm.py                   étape 3b, appel au modèle de langage (Claude ou Ollama)
│   ├── telegram_app.py          étape 4, l'adaptateur Telegram (un bot par persona)
│   ├── logs.py                  configuration des logs et mode debug
│   └── cli.py                   la commande `persona`
└── tests/                       tests automatisés (pytest)
```

Pourquoi un dossier `src/` ? Le code est un **package** installé dans l'environnement : on
l'importe partout de la même façon (`from persona_bot.bot import PersonaBot`), et les tests
utilisent exactement le code installé, pas un fichier trouvé par hasard dans le dossier courant.

## Développement

```bash
uv run pytest            # lance les tests (quelques secondes, sans clé API ni modèle)
uv run ruff check .      # vérifie le style et détecte des erreurs courantes
uv run ruff format .     # formate le code
```

Les tests remplacent le modèle d'embeddings et le modèle de langage (Claude ou Ollama) par
de faux objets : c'est possible parce que `PersonaBot` accepte qu'on lui passe son `retriever`
et son `client` (*injection de dépendances*). Ils utilisent aussi une persona de test
(`tests/conftest.py`) plutôt que celle de JCVD, pour vérifier le mécanisme sans dépendre du
texte d'une vraie persona. Ils vérifient la lecture des personas, le nettoyage des citations,
la gestion des historiques, le cas sans citations, et le démarrage et l'arrêt des bots Telegram.

## Licence

Le code est sous licence [MIT](LICENSE) : tu peux le réutiliser, le modifier et le
redistribuer librement, en conservant la mention de copyright. Les citations de
`personas/jcvd/citations.md`, `personas/godefroy/citations.md` et
`personas/jacquouille/citations.md` appartiennent à leurs auteurs ou ayants droit respectifs et
ne sont pas couvertes par cette licence.

## Pour aller plus loin

Les [exercices du guide](docs/GUIDE_RAG.md#11-exercices) proposent des expériences guidées : régler le
nombre de citations, filtrer par métadonnées, changer de modèle d'embeddings ou de modèle de
langage, créer une persona.

## Migrer depuis JCVD Bot

Le projet s'appelait « JCVD Bot » (dépôt `JeanClaude`, commande `jcvd`). Il continue dans un
nouveau dépôt, `persona-bot`, qui reprend tout son historique ; l'ancien dépôt `JeanClaude`
reste en ligne, figé à la version JCVD Bot. Pour passer une installation existante au nouveau
projet :

1. **Le dépôt et le dossier.** Pointe ton clone vers le nouveau dépôt, récupère la nouvelle
   version, puis renomme le dossier :
   ```bash
   git remote set-url origin git@github.com:glimberger/persona-bot.git
   git pull
   cd .. && mv JeanClaude persona-bot && cd persona-bot
   rm -rf .venv && uv sync   # un .venv ne survit pas au déplacement de son dossier
   ```
2. **`.env`** : renomme `TELEGRAM_BOT_TOKEN` en `TELEGRAM_TOKEN_JCVD`, et `JCVD_DEBUG` en
   `PERSONA_DEBUG`. Si tu oublies le token, `persona telegram` refuse de démarrer et te dit
   quoi faire.
3. **L'index** : il est maintenant rangé par persona. Reconstruis-le :
   ```bash
   uv run persona ingest && uv run persona index
   ```
   L'ancienne collection (`jcvd_citations`) reste dans `data/chroma/` sans servir. Pour
   repartir d'un index propre : `rm -rf data/chroma` avant ces deux commandes.
4. **Sur le Raspberry Pi** : le service change aussi de nom. Procédure :
   [DEPLOIEMENT_PI.md, section 14](docs/DEPLOIEMENT_PI.md#14-migrer-depuis-jcvd-bot).
