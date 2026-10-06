# Module home-manager qui fait tourner le bot Telegram comme service systemd "utilisateur".
#
# C'est la variante Nix de deploy/persona-bot.service : le même service, mais déclaré dans la
# configuration home-manager de la machine au lieu d'être activé à la main avec
# `systemctl --user enable`. Mode d'emploi : docs/DEPLOIEMENT_PI.md, section 12.
#
# home-manager est l'outil qui décrit l'environnement d'un utilisateur (programmes, fichiers
# de configuration, services) dans des fichiers Nix. Un "module" home-manager déclare des
# options (ce qu'on peut régler) et la configuration qui en découle. Une fois ce fichier
# importé dans sa configuration, il suffit d'écrire :
#
#   services.persona-bot.enable = true;
#
# Ce que le module ne fait PAS : installer le projet. Le bot tourne toujours depuis le dépôt
# cloné, avec l'environnement Python créé par uv (.venv) et les secrets de .env (étapes 6 et 7
# de docs/DEPLOIEMENT_PI.md). Construire le projet lui-même avec Nix serait possible, mais
# demanderait de traduire uv.lock en paquets Nix (PyTorch compris) : beaucoup de complexité
# pour un gain faible ici. Le module ne remplace donc que la partie systemd.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.persona-bot;
in
{
  options.services.persona-bot = {
    enable = lib.mkEnableOption "les bots Telegram persona-bot";

    directory = lib.mkOption {
      type = lib.types.str;
      # %h est remplacé par systemd par le dossier personnel (/home/<utilisateur>).
      default = "%h/projects/persona-bot";
      description = "Dossier du dépôt cloné, qui contient .env et .venv.";
    };

    # uv fourni par Nix : sa version est fixée par la configuration de la machine, au lieu de
    # dépendre d'un uv installé à la main dans ~/.local/bin.
    package = lib.mkPackageOption pkgs "uv" { };
  };

  # lib.mkIf : cette configuration n'existe que si `enable = true`.
  config = lib.mkIf cfg.enable {
    # home-manager écrit ce service dans ~/.config/systemd/user/persona-bot.service, l'active au
    # démarrage et le relance quand sa définition change. Les réglages sont les mêmes que dans
    # deploy/persona-bot.service : garde les deux fichiers synchronisés.
    systemd.user.services.persona-bot = {
      Unit = {
        Description = "Bots Telegram persona-bot (une persona par bot)";
        # Avec Ollama sur le Pi (services.ollama de home-manager, voir docs/DEPLOIEMENT_PI.md) :
        # démarre le bot après lui. Ce n'est qu'un ordre de démarrage, pas une dépendance : sans
        # Ollama (LLM_BACKEND=claude, ou Ollama sur une autre machine), la ligne n'a aucun effet.
        After = [ "ollama.service" ];
      };

      Service = {
        # Le bot cherche .env, .venv et data/ dans le dossier du projet.
        WorkingDirectory = cfg.directory;
        # --env-file : la clé d'API et le token Telegram sont lus dans .env, exactement comme en
        # lançant le bot à la main. --frozen : utilise les versions de uv.lock telles quelles,
        # sans jamais les modifier.
        ExecStart = "${lib.getExe cfg.package} run --frozen --env-file .env persona telegram";
        # Relance le bot 10 s après un plantage. Au démarrage du Pi, si le réseau n'est pas
        # encore prêt, le bot échoue à joindre Telegram, s'arrête, et cette relance fait la
        # suite.
        Restart = "on-failure";
        RestartSec = 10;
        # À l'arrêt, n'envoie le signal SIGTERM qu'au processus principal (uv), qui le transmet
        # à Python. Par défaut, systemd l'envoie à tous les processus du service : Python le
        # recevait deux fois (de systemd et de uv), et le second interrompait l'arrêt propre de
        # la librairie Telegram (avertissement "coroutine 'Updater.stop' was never awaited", et
        # derniers messages pas marqués comme lus, donc possiblement traités une seconde fois
        # au redémarrage).
        KillMode = "mixed";
        Environment = [
          # Sans ça, Python garde ses logs en mémoire tampon et ils arrivent en retard dans le
          # journal.
          "PYTHONUNBUFFERED=1"
          # Pas de barres de progression (chargement du modèle) : dans le journal, elles
          # deviennent des lignes illisibles ("[146B blob data]").
          "TQDM_DISABLE=1"
        ];
      };

      # Démarre avec la session de l'utilisateur, ouverte dès le boot grâce à "linger".
      Install.WantedBy = [ "default.target" ];
    };
  };
}
