{
  description = "Software defined LaserDisc decoder";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        python = pkgs.python312;
        pythonPackages = python.pkgs;
        
        # PEP-440 compatible version string (for package metadata)
        version = "7.2.0";
        
        # Use flake's built-in git properties
        # dirtyShortRev already includes "-dirty" suffix, so we need to handle it
        gitCommit = if self ? dirtyShortRev then self.dirtyShortRev else self.shortRev;
        gitDirty = self ? dirtyRev;
        
        # Build PEP-440 compliant version string with git info
        # Format: base_version+git.commit[.dirty]
        # dirtyShortRev format is "abc1234-dirty", so replace "-" with "."
        fullVersion = "${version}+git.${builtins.replaceStrings ["-"] ["."] gitCommit}";
        
        ld-decode = pythonPackages.buildPythonPackage {
          pname = "ld-decode";
          inherit version;
          
          src = ./.;
          
          pyproject = true;
          
          nativeBuildInputs = with pythonPackages; [
            setuptools
            wheel
            pkgs.git
          ];
          
          propagatedBuildInputs = with pythonPackages; [
            av
            matplotlib
            numba
            numpy
            scipy
          ];
          
          # Write PEP-440 compliant version file with git info
          preBuild = ''
            echo "${fullVersion}" > lddecode/version
          '';
          
          # Skip tests for minimal build
          doCheck = false;
          
          meta = with pkgs.lib; {
            description = "Software defined LaserDisc decoder";
            homepage = "https://github.com/happycube/ld-decode";
            license = licenses.gpl3Plus;
            maintainers = [ ];
          };
        };
      in
      {
        packages = {
          default = ld-decode;
          ld-decode = ld-decode;
        };
        
        apps = {
          default = {
            type = "app";
            program = "${ld-decode}/bin/ld-decode";
          };
          ld-decode = {
            type = "app";
            program = "${ld-decode}/bin/ld-decode";
          };
          ld-ldf-reader-py = {
            type = "app";
            program = "${ld-decode}/bin/ld-ldf-reader-py";
          };
        };
        
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pkgs.cmake
            pkgs.ffmpeg
            ld-decode
            python
            pythonPackages.av
            pythonPackages.matplotlib
            pythonPackages.numba
            pythonPackages.numpy
            pythonPackages.scipy
            pythonPackages.jupyter
            pythonPackages.pandas
            pythonPackages.pytest
            pythonPackages.pytest-cov
          ];
          
          shellHook = ''
            echo "ld-decode development environment"
          '';
        };
      }
    );
}
