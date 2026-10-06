# Déployer les bots sur un Raspberry Pi

Ce document décrit l'installation des bots Telegram (un par persona, tous servis par le même
programme) sur un Raspberry Pi pour qu'ils tournent en permanence, telle qu'elle a été faite
pour ce projet. Tu as installé le projet quand il s'appelait « JCVD Bot » ? Voir la
[section 14](#14-migrer-depuis-jcvd-bot). Tous les chiffres ont été mesurés sur
un **Raspberry Pi 5 avec 8 Go de RAM** et une carte microSD de 128 Go, avec Claude comme
modèle de langage.

On installe le Pi **sans écran ni clavier** : tout se fait depuis ton ordinateur, par **SSH**
(un accès en ligne de commande à distance, chiffré).

---

## 1. Matériel

- Un Raspberry Pi 5 (8 Go conseillés : le bot utilise environ 1,1 Go de mémoire).
- Une carte microSD (au moins 16 Go ; sur ce Pi, système et projet compris, 5,7 Go sont
  utilisés après avoir vidé le cache de `uv`, voir l'étape 6).
- L'alimentation officielle 27 W (USB-C, 5 V / 5 A). Avec un chargeur plus faible, le Pi 5
  limite le courant de ses ports USB et peut ralentir.
- Un câble Ethernet si possible : plus fiable que le Wi-Fi pour un bot allumé en permanence.

---

## 2. Préparer la carte SD

Tout se fait avec **Raspberry Pi Imager**, qui efface et prépare la carte lui-même (inutile
de la formater avant) :

```bash
brew install --cask raspberry-pi-imager   # sur Mac ; sinon : raspberrypi.com/software
```

Dans Imager, choisis :

- **Appareil** : Raspberry Pi 5 ;
- **Système** : *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**. « Lite » = sans
  bureau graphique, inutile ici, ce qui laisse la mémoire au bot. « 64-bit » est obligatoire :
  PyTorch n'existe pas pour les systèmes ARM 32 bits ;
- **Stockage** : ta carte (vérifie bien que ce n'est pas un autre disque).

Puis **Modifier les réglages** :

- **Nom d'hôte** : par exemple `agent-pi`. Le Pi sera joignable à l'adresse `agent-pi.local` ;
- **Nom d'utilisateur** et mot de passe ;
- **Wi-Fi** (nom du réseau, mot de passe, pays `FR`), sauf si tu branches un câble Ethernet ;
- **Fuseau horaire** et clavier ;
- **Services** : active SSH avec **« Autoriser uniquement l'authentification par clé
  publique »**, et colle la clé publique créée à l'étape suivante.

---

## 3. Une clé SSH dédiée au Pi

Une **clé SSH** est une paire de fichiers : une clé privée, qui reste sur ton ordinateur, et
une clé publique, que tu donnes au Pi. Le Pi n'accepte que la personne qui détient la clé
privée : pas de mot de passe à deviner. Une clé **dédiée** au Pi se révoque sans toucher à
tes autres accès (GitHub, serveurs…).

Dans ton terminal (la commande demande une phrase de passe, qui chiffre la clé privée sur
ton disque) :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/agent-pi -C "agent-pi"
ssh-add --apple-use-keychain ~/.ssh/agent-pi   # sur Mac : phrase de passe gardée dans le trousseau
cat ~/.ssh/agent-pi.pub                        # la clé publique, à coller dans Imager
```

Ajoute ensuite une entrée dans `~/.ssh/config`, pour te connecter avec un simple
`ssh agent-pi` :

```
Host agent-pi
  HostName agent-pi.local
  User <ton-utilisateur>
  IdentityFile ~/.ssh/agent-pi
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
```

`IdentitiesOnly yes` fait que seule cette clé est présentée au Pi. `HostName` doit
correspondre au nom d'hôte **réellement** configuré dans Imager, suivi de `.local`.

---

## 4. Premier démarrage et connexion

Insère la carte, branche l'alimentation, et attends **2 à 5 minutes** : au premier démarrage,
le Pi agrandit sa partition puis redémarre. Ensuite :

```bash
ssh -o StrictHostKeyChecking=accept-new agent-pi
```

À la première connexion, SSH enregistre l'« empreinte » du Pi (un identifiant qui prouve que
c'est bien lui). `accept-new` l'accepte cette fois-ci, et SSH refusera la connexion si elle
change un jour, ce qui pourrait signaler une usurpation.

**Si le nom `agent-pi.local` est introuvable** :

- le Pi n'a peut-être pas fini de démarrer, ou n'est pas sur le réseau (erreur de mot de
  passe Wi-Fi : le câble Ethernet évite ce problème) ;
- il a peut-être un autre nom : sur ce projet, Imager avait enregistré `ai-pi` au lieu du nom
  voulu. La page d'administration de ta box (souvent <http://192.168.1.1>) liste les appareils
  connectés et leur nom. Mets le bon nom dans `HostName`, puis renomme le Pi à l'étape 5 si
  tu veux.

---

## 5. Mettre le système à jour

Sur les versions récentes de Raspberry Pi OS (celle utilisée ici est basée sur Debian 13,
« trixie »), `sudo` demande le mot de passe de l'utilisateur. Lance donc ces commandes depuis
**ton terminal**, avec `ssh -t` : le `-t` ouvre une session interactive où `sudo` peut te
demander ce mot de passe.

```bash
ssh -t agent-pi '
sudo apt update && sudo apt full-upgrade -y &&
sudo apt install -y git &&
sudo loginctl enable-linger $USER'
```

- `apt update && apt full-upgrade` : met à jour tous les paquets (correctifs de sécurité) ;
- `apt install git` : pour récupérer le projet ;
- `loginctl enable-linger` : autorise tes services **utilisateur** (voir étape 9) à démarrer
  avec le Pi, sans que tu sois connecté. C'est la dernière commande qui demande `sudo`.

**Renommer le Pi** (facultatif), dans la même session :

```bash
sudo hostnamectl set-hostname agent-pi
sudo sed -i "s/^127\.0\.1\.1\s.*/127.0.1.1\tagent-pi/" /etc/hosts
sudo systemctl restart avahi-daemon
```

La 2e ligne met à jour le fichier où le Pi associe son propre nom à son adresse (sans elle,
`sudo` afficherait « unable to resolve host »). **Avahi** est le service qui annonce le nom
`xxx.local` sur le réseau : on le relance pour qu'il annonce le nouveau nom. Pense à mettre à
jour `HostName` dans `~/.ssh/config`.

---

## 6. Installer uv et le projet

`uv` s'installe dans ton dossier personnel, sans `sudo`, puis installe lui-même le Python
dont le projet a besoin :

```bash
ssh agent-pi
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env        # ajoute ~/.local/bin au PATH dans cette session

mkdir -p ~/projects && cd ~/projects
git clone https://github.com/glimberger/persona-bot.git
cd persona-bot
uv sync                        # environnement Python et dépendances (~1,3 Go)
uv run persona ingest && uv run persona index
uv run persona eval            # doit donner les mêmes scores que sur ton ordinateur
```

Le dépôt étant public, le Pi le clone en HTTPS : il n'a besoin d'aucun accès à ton compte
GitHub. `persona index` télécharge le modèle d'embeddings (quelques centaines de Mo) à son
premier lancement : **47 s** au total sur le Pi. `persona eval` y donne exactement les mêmes
scores que sur le Mac de développement.

### PyTorch : la version CPU, pas la version CUDA

Sur Linux ARM, le PyTorch du dépôt de paquets par défaut (PyPI) est compilé pour les cartes
graphiques NVIDIA (**CUDA**) et embarque plusieurs Go de bibliothèques inutiles sur un Pi.
`pyproject.toml` indique donc à `uv` de prendre, **sur Linux uniquement**, la version « CPU »
publiée par PyTorch (section `[tool.uv.sources]`). Mesuré sur le Pi :

| | PyTorch CUDA | PyTorch CPU (choix du projet) |
|---|---|---|
| Taille de `.venv` | 5,6 Go | **1,3 Go** |
| Mémoire maximale (chargement + recherches) | 1 497 Mo | **1 155 Mo** |
| Une recherche | 60 ms | 60 ms |

Sur Mac, la question ne se pose pas : le PyTorch par défaut n'y contient pas CUDA.

### Place occupée

Mesuré sur le Pi : le dossier du projet occupe 1,3 Go (presque tout pour `.venv`), le modèle
d'embeddings 458 Mo (dans `~/.cache/huggingface`), et le **cache de `uv`** 5,0 Go. Ce cache
garde une copie des paquets téléchargés, pour réinstaller sans rien retélécharger ; ici, il
contenait encore la version CUDA de PyTorch installée lors d'un premier essai. Tu peux le vider
sans risque (ici, 5,0 Go libérés : la carte est passée de 11 Go à 5,7 Go utilisés) :

```bash
systemctl --user stop persona-bot     # si le service est déjà installé (étape 9)
uv cache clean                     # la prochaine réinstallation complète retéléchargera les paquets
systemctl --user start persona-bot
```

Arrête d'abord le bot : `uv run`, qui le fait tourner, verrouille le cache pour qu'on ne
supprime pas des fichiers en cours d'utilisation. Sinon, `uv cache clean` attend
indéfiniment que ce verrou se libère.

### Déplacer le projet ? Recrée `.venv`

`.venv` contient des **chemins absolus** (vers le Python de l'environnement et vers le
projet). Si tu déplaces le dossier du projet, supprime-le et recrée-le :

```bash
rm -rf .venv && uv sync        # 2 s : les paquets sont déjà dans le cache de uv
```

---

## 7. Copier les secrets

Le fichier `.env` (clés et token, voir [`.env.example`](../.env.example)) n'est pas sur
GitHub, et c'est voulu. Copie-le depuis ton ordinateur :

```bash
ssh agent-pi 'umask 077; cat > ~/projects/persona-bot/.env' < .env
```

`umask 077` fait que le fichier est créé directement avec des droits réservés à ton
utilisateur (`-rw-------`), sans instant où il serait lisible par d'autres. `HF_HUB_OFFLINE=1`
convient au Pi, puisque le modèle d'embeddings y est déjà téléchargé.

**Arrête les bots sur ton ordinateur** s'ils tournent : Telegram n'accepte qu'un programme à
la fois par bot (voir le README, [erreur « Une autre instance du bot
tourne déjà »](../README.md#étape-4--brancher-les-personas-sur-telegram-persona-telegram-telegram_apppy)).

Test de bout en bout, depuis le Pi :

```bash
uv run --env-file .env persona ask jcvd "J'ai peur d'échouer"
```

Mesuré : **6,8 s** pour la réponse complète (recherche des citations comprise), comme sur le
Mac. C'est Claude qui fait l'essentiel du travail, pas le Pi.

---

## 8. Pourquoi un service

Lancer `persona telegram` dans un terminal ne suffit pas : les bots s'arrêtent dès que tu fermes la
session, et il ne redémarre ni après une coupure de courant ni après un plantage. On le confie
donc à **systemd**, le gestionnaire de services de Linux, qui démarre les programmes au boot,
les relance s'ils plantent et collecte leurs logs.

Le fichier [`deploy/persona-bot.service`](../deploy/persona-bot.service) décrit le service
(chaque ligne y est commentée). C'est un **service utilisateur** : il tourne sous ton compte,
sans droits administrateur, et se gère sans `sudo`. Il :

- lance `uv run --frozen --env-file .env persona telegram` depuis le dossier du projet
  (`--frozen` : utilise `uv.lock` tel quel, sans jamais le modifier) ;
- relance le bot 10 s après un plantage (`Restart=on-failure`). Si le réseau n'est pas prêt
  au démarrage, le bot s'arrête faute de joindre Telegram, et c'est cette relance qui fait la
  suite ;
- à l'arrêt, n'envoie le signal d'arrêt (`SIGTERM`) qu'à `uv`, qui le transmet au bot
  (`KillMode=mixed`). Par défaut, systemd l'envoie à tous les processus du service : le bot le
  recevait deux fois, une fois de systemd et une fois de `uv`, et le second interrompait son
  arrêt propre. Les journaux montraient alors
  `RuntimeWarning: coroutine 'Updater.stop' was never awaited`, et les derniers messages
  n'étaient pas marqués comme lus auprès de Telegram : ils pouvaient être traités une seconde
  fois au redémarrage ;
- démarre avec le Pi, grâce au réglage « linger » de l'étape 5.

---

## 9. Installer et gérer le service

Si ton Pi est géré avec Nix et home-manager, installe plutôt le service avec le module de la
[section 12](#12-variante-avec-nix-et-home-manager) ; les commandes utiles ci-dessous restent
les mêmes.

```bash
ssh agent-pi
systemctl --user enable --now ~/projects/persona-bot/deploy/persona-bot.service
```

`enable` crée un lien vers le fichier du dépôt (il sera donc à jour après un `git pull`) et
active le démarrage au boot ; `--now` le démarre tout de suite.

Commandes utiles :

```bash
systemctl --user status persona-bot       # état du service
systemctl --user restart persona-bot      # redémarrer le bot
systemctl --user stop persona-bot         # l'arrêter (par exemple pour tester sur ton ordinateur)
journalctl --user-unit persona-bot -f     # suivre les logs en direct (Ctrl+C pour quitter)
```

**Attention à la commande des logs** : `journalctl --user -u persona-bot` ne trouve rien ici,
car les logs des services utilisateur arrivent dans le journal du système. `--user-unit` les
y retrouve ; ton compte y a accès parce qu'il fait partie du groupe `adm`.

Le service ajoute deux variables : `PYTHONUNBUFFERED=1` (les logs arrivent tout de suite dans
le journal, au lieu d'attendre en mémoire tampon) et `TQDM_DISABLE=1` (pas de barre de
progression au chargement du modèle, qui apparaîtrait comme une ligne illisible
`[146B blob data]`).

Pour le mode debug, ajoute `PERSONA_DEBUG=1` dans `.env` puis redémarre le service (voir le
README, [Mode debug](../README.md#mode-debug)).

---

## 10. Mettre à jour les bots

```bash
ssh agent-pi
cd ~/projects/persona-bot
git pull
uv run persona ingest && uv run persona index   # seulement si des citations ont changé
systemctl --user restart persona-bot
```

`uv run` remet l'environnement à jour tout seul si `uv.lock` a changé.

**Ajouter une persona sur le Pi** : après le `git pull` qui l'apporte, ajoute son
`TELEGRAM_TOKEN_<SLUG>` dans le `.env` du Pi (`nano ~/projects/persona-bot/.env`), puis
redémarre le service. Au démarrage, le journal affiche une ligne `Bot @…_bot démarré` par
persona.

---

## 11. Mesures sur le Pi

| | Raspberry Pi 5 (8 Go) |
|---|---|
| Du boot au bot prêt | 26 s (service lancé 8 s après le boot, prêt 18 s plus tard) |
| Chargement du modèle d'embeddings | 10,5 à 16,5 s selon les essais |
| Une recherche de citations | 60 ms (6 ms sur un Mac M5) |
| Réponse complète avec Claude | 6,8 s |
| Mémoire du bot en service (persona JCVD seule) | environ 1,1 Go (6,7 Go restent libres) |
| Environnement Python (`.venv`) | 1,3 Go (+ 458 Mo pour le modèle d'embeddings) |
| Température | 47 à 49 °C, aucun ralentissement (`vcgencmd get_throttled` = `0x0`) |

Ces mesures datent de l'époque où le programme ne servait que JCVD. Une persona sans
citations ne charge pas de second modèle d'embeddings (il est partagé, et elle n'en a de
toute façon pas besoin) : elle devrait ajouter peu de mémoire, mais ce n'est pas encore
mesuré sur le Pi.

Avec Ollama sur le Pi (`LLM_BACKEND=ollama`), c'est le Pi lui-même qui écrit la réponse : de
48 à 89 s avec `ministral-3:3b`. Mesures complètes et explication dans la
[section 13](#13-ollama-sur-le-pi).

---

## 12. Variante avec Nix et home-manager

Cette section ne te concerne que si tu gères déjà ton Pi avec **Nix** (un gestionnaire de
paquets qui décrit un environnement dans des fichiers texte) et **home-manager** (l'outil Nix
qui décrit l'environnement d'un utilisateur : programmes, fichiers de configuration,
services). C'est le cas du Pi de ce projet.

Au lieu d'activer `deploy/persona-bot.service` à la main (étape 9), tu déclares le service dans
ta configuration home-manager. Le fichier [`deploy/persona-bot.nix`](../deploy/persona-bot.nix)
est un **module** home-manager : il décrit le même service que `deploy/persona-bot.service`,
et home-manager se charge de l'écrire, de l'activer au démarrage et de le relancer quand sa
définition change.

Le module ne remplace que la partie systemd. Le bot tourne toujours depuis le dépôt cloné,
avec son `.venv` et son `.env` : les étapes 1 à 7 restent nécessaires, réglage « linger » de
l'étape 5 compris.

### Importer le module

Dans le `flake.nix` de ta configuration, ajoute le dépôt en entrée. `flake = false` : on veut
seulement ses fichiers, pas un flake.

```nix
inputs.persona-bot = {
  url = "github:glimberger/persona-bot";
  flake = false;
};
```

Puis, dans les modules de la configuration home-manager du Pi :

```nix
modules = [
  # … tes autres modules
  "${persona-bot}/deploy/persona-bot.nix"
];
```

Et dans la configuration du Pi :

```nix
services.persona-bot.enable = true;
```

| Option | Par défaut | Rôle |
|---|---|---|
| `services.persona-bot.enable` | `false` | active le service |
| `services.persona-bot.directory` | `%h/projects/persona-bot` | dossier du dépôt cloné (`%h` : ton dossier personnel) |
| `services.persona-bot.package` | `pkgs.uv` | le `uv` qui lance le bot |

### Passer du service manuel au module

Si tu as suivi l'étape 9, désactive d'abord l'ancien service : son lien dans
`~/.config/systemd/user/` gênerait home-manager, qui veut y écrire son propre fichier.

```bash
systemctl --user disable --now persona-bot
home-manager switch --flake <ta-configuration>
```

Le bot est arrêté entre ces deux commandes. Pour réduire cette coupure, construis d'abord la
configuration (`home-manager build --flake <ta-configuration>`) : le `switch` n'a plus alors
qu'à l'activer. Mesuré sur ce Pi : **5 s** de coupure.

Les commandes de l'étape 9 (`status`, `restart`, logs) et la mise à jour du bot (étape 10)
ne changent pas.

### Mettre à jour le module

Ta configuration fige la version du dépôt dans son `flake.lock`. Après une modification de
`deploy/persona-bot.nix`, un `git pull` du projet ne suffit pas : mets à jour l'entrée dans ta
configuration, puis applique-la.

```bash
nix flake update persona-bot
home-manager switch --flake <ta-configuration>
```

---

## 13. Ollama sur le Pi

Par défaut, le bot confie l'écriture des réponses à Claude, sur les serveurs d'Anthropic. Avec
`LLM_BACKEND=ollama`, il peut aussi utiliser un modèle local, exécuté par Ollama sur le Pi
lui-même : gratuit, et rien ne part chez Anthropic. Le README explique ce qui change dans le
code et compare les modèles sur Mac ([Choisir le modèle de
langage](../README.md#choisir-le-modèle-de-langage--claude-ou-ollama)). Cette section décrit
l'installation sur le Pi et ce qu'on y a mesuré.

**En bref** : ça fonctionne, mais une réponse prend environ une minute, contre 7 s avec
Claude. Le bot de ce projet reste donc sur Claude ; Ollama est installé sur le Pi pour
expérimenter, et passer de l'un à l'autre ne demande qu'une ligne dans `.env`.

### Installer Ollama

**Avec home-manager** (le cas de ce Pi), dans la configuration du Pi :

```nix
services.ollama = {
  enable = true;
  acceleration = false;               # le Pi 5 n'a pas de GPU utilisable par Ollama
  environmentVariables = {
    OLLAMA_CONTEXT_LENGTH = "4096";
    OLLAMA_KEEP_ALIVE = "-1";
  };
};
```

Puis `home-manager switch --flake <ta-configuration>`. home-manager crée un service
utilisateur `ollama.service`, comme celui du bot. Il n'écoute que sur le Pi
(`127.0.0.1:11434`) : la valeur par défaut d'`OLLAMA_BASE_URL` (`http://localhost:11434`)
convient donc, sans rien ouvrir sur le réseau. Le service du bot démarre après lui
(`After=ollama.service` dans [`deploy/persona-bot.service`](../deploy/persona-bot.service) et
`deploy/persona-bot.nix`). Ce n'est qu'un ordre de démarrage : sans Ollama, la ligne n'a aucun
effet.

**Sans Nix**, le script officiel installe Ollama comme service **système** (il demande
`sudo`) : `curl -fsSL https://ollama.com/install.sh | sh`. Les deux réglages ci-dessus se
mettent alors dans `sudo systemctl edit ollama`, sous `[Service]`
(`Environment=OLLAMA_CONTEXT_LENGTH=4096`, etc.). Un service utilisateur ne peut pas se ranger
après un service système : `After=ollama.service` reste alors sans effet, ce qui ne gêne pas
(voir plus bas). Cette variante n'a pas été testée sur ce Pi.

### Télécharger le modèle et brancher le bot

```bash
ollama pull ministral-3:3b             # 3,0 Go, 1 min 24 s sur ce Pi
```

Dans le `.env` du Pi, ajoute `LLM_BACKEND=ollama`, puis redémarre le bot
(`systemctl --user restart persona-bot`). Pour revenir à Claude, retire la ligne (ou mets
`LLM_BACKEND=claude`) et redémarre. Garde ta clé d'API Anthropic dans `.env` : tu pourras ainsi
revenir à Claude sans recopier la clé.

Vérifie avec `ollama ps`, après un premier message : la colonne `PROCESSOR` doit afficher
`100% CPU` et `CONTEXT` `4096`.

### Les deux réglages

- **`OLLAMA_CONTEXT_LENGTH=4096`** : la taille de la fenêtre de contexte. Les requêtes du bot
  restent sous 1 500 tokens (README, [La fenêtre de
  contexte](../README.md#choisir-le-modèle-de-langage--claude-ou-ollama)) ; une fenêtre plus
  petite occupe moins de mémoire.
- **`OLLAMA_KEEP_ALIVE=-1`** : garder le modèle en mémoire indéfiniment. Par défaut, Ollama
  le décharge après 5 minutes sans requête, et le message suivant attend qu'il soit relu sur
  la carte SD : 35,6 s pour `ministral-3:3b`, en plus de la réponse. Le prix : 3,1 Go de
  mémoire occupés en permanence une fois le modèle chargé. Ollama ne charge le modèle qu'à la
  première requête : tant que le bot reste sur Claude, ce réglage ne coûte rien.

Le tout premier message après l'installation a pris **143,6 s** : le modèle était lu pour la
première fois sur la carte SD.

### Mesures

Ollama 0.34.4 sur le Pi 5 (8 Go), modèle déjà chargé (sauf la colonne « Chargement »).
5 questions, chacune dans une conversation neuve, avec `uv run persona ask jcvd` : « J'ai peur
d'échouer », « Comment devenir meilleur ? », « C'est quoi le bonheur pour toi ? », « Je
n'arrive pas à me motiver le matin », « Que penses-tu de l'amour ? ».

| Modèle | Mémoire | Chargement | Durée par réponse | Mots (cible 60–120) | Phrases (cible 2–3) | Lecture | Écriture |
|---|---|---|---|---|---|---|---|
| `ministral-3:3b` | 3,1 Go | 35,6 s | 48,0 à 89,3 s | 118 à 233 | 6 à 9 | 20,9 tokens/s | 3,3 tokens/s |
| `gemma3:4b` | 3,4 Go | 41,2 s | 77,6 à 106,9 s | 128 à 175 | 10 à 18 | 21,3 tokens/s | 3,8 tokens/s |
| `gemma3:1b` | 1,2 Go | 2,7 s | 5,7 à 19,7 s | 4 à 44 | 1 à 4 | 51,2 tokens/s | 13,5 tokens/s |
| Claude (rappel, [section 11](#11-mesures-sur-le-pi)) | — | — | 6,8 s | | | | |

« Mémoire » est la colonne `SIZE` de `ollama ps`. « Lecture » et « Écriture » viennent des
compteurs d'Ollama (`prompt_eval_duration` et `eval_duration` de son API), mesurés sur une
requête à part : le même texte, compté 920 tokens par Gemma et 1 613 par Ministral (chaque
modèle découpe le texte à sa façon). Le cache de fichiers de Linux n'a pas pu être vidé entre
deux modèles : les temps de chargement sont donc un peu optimistes. Pendant les mesures, le Pi
est monté à 72 °C, sans ralentissement (`vcgencmd get_throttled` = `0x0`).

**Pourquoi c'est si lent ?** Un modèle de langage écrit un token à la fois, et chaque token
demande de parcourir tous les paramètres du modèle en mémoire. Lire le prompt va plus vite,
car tous ses tokens se traitent ensemble. Pour `ministral-3:3b`, une réponse de 250 tokens
prend donc environ 75 s rien qu'à l'écriture (250 ÷ 3,3), alors que relire la partie nouvelle
du prompt (environ 150 tokens, le reste venant du cache) prend quelques secondes. Le premier
message d'une conversation est plus long : sans cache, les 900 tokens du prompt se lisent en
plus de 40 s. Les modèles trop bavards le paient doublement, car chaque mot en trop ajoute du
temps d'attente.

**Un modèle plus petit ?** `gemma3:1b` répond en 6 à 20 s, mais ses réponses sont
inutilisables : « L'échec, tu comprends ? » (4 mots) pour « J'ai peur d'échouer », ou des
phrases qui n'existent pas en français (« une énergie qui ne se loin de passera sans
nuisserie »). Un milliard de paramètres ne suffit pas pour tenir ce prompt.

Pendant l'attente, Telegram affiche « en train d'écrire… » jusqu'à la réponse (README,
[Points de conception](../README.md#étape-4--brancher-les-personas-sur-telegram-persona-telegram-telegram_apppy)).

---

## 14. Migrer depuis JCVD Bot

Le projet s'appelait « JCVD Bot » : dépôt `JeanClaude`, service `jcvd-bot`, commande `jcvd`.
Sur un Pi installé à cette époque, le service, le dossier, deux variables de `.env` et l'index
changent de nom. Le résumé côté ordinateur est dans le README,
[Migrer depuis JCVD Bot](../README.md#migrer-depuis-jcvd-bot) ; voici la procédure sur le Pi.

**Arrête et désactive l'ancien service en premier**, avant le `git pull` : systemd le lance
depuis `deploy/jcvd-bot.service`, que le pull supprime. Désactivé après coup, il laisserait
un lien cassé dans `~/.config/systemd/user/`.

```bash
ssh agent-pi
systemctl --user disable --now jcvd-bot

cd ~/projects/JeanClaude
git remote set-url origin https://github.com/glimberger/persona-bot.git
git pull

# Nouveau nom du dossier. .venv contient des chemins absolus : on le recrée (étape 6).
cd .. && mv JeanClaude persona-bot && cd persona-bot
rm -rf .venv && uv sync

# .env : un token par persona, et le nouveau nom de la variable de debug.
sed -i 's/^TELEGRAM_BOT_TOKEN=/TELEGRAM_TOKEN_JCVD=/; s/^JCVD_DEBUG=/PERSONA_DEBUG=/' .env

# L'index est maintenant rangé par persona (collection citations_jcvd) : on le reconstruit.
rm -rf data/chroma && uv run persona ingest && uv run persona index
uv run persona eval            # mêmes scores qu'avant la migration

systemctl --user enable --now ~/projects/persona-bot/deploy/persona-bot.service
journalctl --user-unit persona-bot -f
```

Dans le journal, `Bot @…_bot démarré (persona jcvd)` confirme que tout fonctionne. Les bots
sont arrêtés depuis la première commande : compte quelques minutes de coupure, l'essentiel
pour reconstruire l'index.

**Avec Nix et home-manager** ([section 12](#12-variante-avec-nix-et-home-manager)) : fais
toutes les étapes ci-dessus sauf les deux commandes `systemctl` (home-manager gère le
service). Dans ta configuration, renomme l'entrée `jeanclaude` en `persona-bot` (nouvelle
adresse `github:glimberger/persona-bot`), importe `deploy/persona-bot.nix` au lieu de
`deploy/jcvd-bot.nix` et remplace `services.jcvd-bot` par `services.persona-bot`. Puis :

```bash
nix flake update persona-bot
home-manager switch --flake <ta-configuration>
```

home-manager supprime alors l'ancien service et installe le nouveau.
