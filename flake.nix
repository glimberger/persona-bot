# Environnement de développement du projet, décrit avec Nix.
#
# Nix est un gestionnaire de paquets qui décrit un environnement dans un fichier texte : toute
# personne qui a Nix obtient exactement les mêmes outils, aux mêmes versions (figées dans
# flake.lock), sans rien installer à la main. Ce fichier est optionnel : sans Nix, suis
# l'installation du README avec uv seul.
#
#   nix develop        ouvre un shell avec Python et uv
#   direnv allow       ou, avec direnv : le shell s'active tout seul en entrant dans le dossier
#                      (.envrc contient `use flake`)
#
# Nix ne fournit que les outils (Python, uv). Les dépendances Python du projet restent gérées
# par uv dans .venv, à partir de pyproject.toml et uv.lock : c'est uv qui fait foi, et le
# projet s'installe de la même façon avec ou sans Nix.
{
  description = "persona-bot : environnement de développement (Python + uv)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      # Les systèmes pris en charge : Mac Apple Silicon et Linux, dont le Raspberry Pi
      # (aarch64-linux). nixpkgs ne prend plus en charge les Mac Intel (x86_64-darwin).
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];

      # Construit { aarch64-darwin = …; aarch64-linux = …; … } en appelant `f` avec les
      # paquets de chaque système, pour ne pas écrire trois fois le même shell.
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        # `nix develop` utilise `default` quand on ne nomme pas de shell.
        default = pkgs.mkShell (
          {
            packages = [ pkgs.uv ] ++ pkgs.lib.optional pkgs.stdenv.isDarwin pkgs.python3;
          }
          # Sur Mac : uv crée .venv avec le Python de ce shell, au lieu d'en télécharger un ou
          # d'en prendre un autre trouvé sur la machine. Piège évité : un .venv lié à un Python
          # installé ailleurs (par exemple par Homebrew) casse dès que ce Python disparaît.
          # Quand Nix met Python à jour, uv recrée .venv tout seul au prochain `uv run`.
          // pkgs.lib.optionalAttrs pkgs.stdenv.isDarwin {
            UV_PYTHON = "${pkgs.python3}/bin/python3";
            UV_PYTHON_DOWNLOADS = "never";
          }
          # Sur Linux (le Raspberry Pi), surtout pas le Python de Nix. Les paquets binaires de
          # PyPI (numpy, torch…) sont compilés pour un Linux classique et chargent des
          # bibliothèques système comme libstdc++.so.6. Un Python de Nix ne les cherche que
          # dans /nix/store : "ImportError: libstdc++.so.6: cannot open shared object file"
          # dès `import numpy`. uv utilise donc son propre Python (téléchargé une fois dans
          # ~/.local/share/uv/python), compilé pour un Linux classique. Limite : sous NixOS,
          # qui n'a pas de /usr/lib, ce Python-là ne démarre pas sans nix-ld.
          // pkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
            UV_PYTHON_PREFERENCE = "only-managed";
          }
        );
      });
    };
}
