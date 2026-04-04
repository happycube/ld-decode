{
  description = "Software defined LaserDisc decoder";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils";
    # Public repo containing ac3rf-decode (C++ library + Python bindings).
    ldaudio = {
      url = "git+https://bitbucket.org/staffanulfberg/ldaudio?submodules=1";
      flake = false;
    };
    # nanobind v2.4.0 — pre-fetched as a flake input so CMake's FetchContent
    # step can run offline inside the Nix sandbox without network access.
    nanobind-src = {
      url = "github:wjakob/nanobind/v2.4.0";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, flake-utils, ldaudio, nanobind-src }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        # On macOS, the default SDK (10.12) predates aligned_alloc (10.15).
        # Bump to 11.0 so C++17 features used by ac3rf are available.
        stdenv = if pkgs.stdenv.isDarwin
                 then pkgs.overrideSDK pkgs.stdenv "11.0"
                 else pkgs.stdenv;

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
        
        docsEnv = pkgs.python3.withPackages (ps: with ps; [
          ps.mkdocs
          ps.mkdocs-material
          ps.mkdocs-awesome-nav
        ]);

        # Build the ac3rf Python extension (nanobind-based C++ module).
        # The FetchContent step for nanobind is satisfied by pointing CMake at
        # the pre-fetched nanobind-src flake input so no network is needed.
        ac3rfPython = python.pkgs.toPythonModule (stdenv.mkDerivation {
          pname = "ac3rf-python";
          version = "0.1.0";

          src = "${ldaudio}/ac3rf-decode";

          strictDeps = true;

          nativeBuildInputs = [ pkgs.cmake pkgs.ninja ];
          buildInputs = [ pkgs.eigen python ];

          cmakeFlags = [
            "-GNinja"
            "-DCMAKE_BUILD_TYPE=Release"
            "-DBUILD_PYTHON=ON"
            "-DBUILD_EXECUTABLE=OFF"
            "-DPython_EXECUTABLE=${python}/bin/python3"
            "-DFETCHCONTENT_SOURCE_DIR_NANOBIND=${nanobind-src}"
            "-DFETCHCONTENT_FULLY_DISCONNECTED=ON"
          ];

          installPhase = ''
            runHook preInstall
            mkdir -p $out/${python.sitePackages}
            find . -name "ac3rf*.so" -exec cp {} $out/${python.sitePackages}/ \;
            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "AC3 RF demodulator Python bindings";
            license = licenses.gpl3Plus;
          };
        });

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
            ac3rfPython
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
          docs = pkgs.stdenv.mkDerivation {
            pname = "ld-decode-docs";
            version = version;
            src = ./.;
            nativeBuildInputs = [ docsEnv ];
            buildPhase = ''mkdocs build'';
            installPhase = ''cp -r site $out'';
          };
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
            docsEnv
            ac3rfPython
          ];
          
          shellHook = ''
            echo "ld-decode development environment"
          '';
        };
      }
    );
}
