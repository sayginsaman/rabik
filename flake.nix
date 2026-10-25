{
  description = "Rabik: macOS voice and AI assistant";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixpkgs-darwin-legacy.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-darwin-legacy,
    }:
    let
      version = builtins.replaceStrings [ "\n" ] [ "" ] (builtins.readFile ./VERSION);
      targetSystems = [
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forEachSystem =
        f:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = f system;
          }) targetSystems
        );
      pkgsFor =
        system:
        if system == "x86_64-darwin" then
          nixpkgs-darwin-legacy.legacyPackages.${system}
        else
          nixpkgs.legacyPackages.${system};
      packageFor =
        system:
        let
          pkgs = pkgsFor system;
        in
        pkgs.writeShellApplication {
          name = "rabik";
          runtimeInputs = [ pkgs.python313 ];
          text = ''
            set -euo pipefail
            src=${./.}
            case "''${1:-}" in
              ""|install|--install|build|--build)
                exec bash "$src/build.sh"
                ;;
              --check)
                for f in "$src/rabik.py" "$src"/brain/*.py; do
                  python3 -c 'import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], "exec")' "$f"
                done
                bash -n "$src/build.sh"
                printf '%s\n' 'rabik source checks passed'
                ;;
              --version)
                printf '%s\n' "rabik ${version}"
                ;;
              --help|-h|help)
                cat <<'EOF'
            Rabik launcher for macOS.

            Usage:
              rabik              Install or update Rabik.app
              rabik --install    Install or update Rabik.app
              rabik --check      Run packaged source checks
              rabik --version    Print the packaged version
              rabik --help       Show this help

            Building requires macOS 26 or later and Apple's command line tools.
            Full use also requires Claude Code (with Claude or a custom server), Devin, or Pi.
            EOF
                ;;
              *)
                printf 'Unknown option: %s\n\n' "$1" >&2
                exec "$0" --help
                ;;
            esac
          '';
          meta = with pkgs.lib; {
            description = "Rabik macOS app launcher";
            homepage = "https://github.com/YOUR_GITHUB/rabik";
            license = licenses.mit;
            mainProgram = "rabik";
            platforms = targetSystems;
          };
        };
    in
    {
      packages = forEachSystem (
        system:
        let
          rabik = packageFor system;
        in
        {
          inherit rabik;
          rabik-mac = rabik;
          source = rabik;
          default = rabik;
        }
      );

      apps = forEachSystem (
        system:
        let
          rabik = self.packages.${system}.default;
          program = "${rabik}/bin/rabik";
          app = {
            type = "app";
            inherit program;
            inherit (rabik) meta;
          };
        in
        {
          rabik = app;
          rabik-mac = app;
          default = app;
        }
      );

      checks = forEachSystem (system: {
        package = self.packages.${system}.default;
      });

      devShells = forEachSystem (system: {
        default =
          let
            pkgs = pkgsFor system;
          in
          pkgs.mkShell {
            packages = [
              pkgs.python313
              pkgs.act
            ];
            shellHook = ''
              echo "Rabik development shell. Building the app requires Apple's command line tools."
            '';
          };
      });

      formatter = forEachSystem (system: (pkgsFor system).nixfmt);
    };
}
