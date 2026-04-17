See build instructions in main readme

# Building and installing vhs-decode from source using pipx
## Install all dependencies required by LD-Decode and VHS-Decode:
Ubuntu/debian based (debian 12/Ubuntu 24.04 or newer base required):

    sudo apt install git python3-dev pipx ffmpeg

For Arch Linux

    pacman -S base-devel git qt5-base qwt fftw ffmpeg pv cmake sox python python-pipx
    
NixOS Linux has pre-made [nur-packages](https://github.com/JuniorIsAJitterbug/nur-packages) for vhs-decode, cxadc and outer tools within the projects.

Install [Rust Compiler](https://www.rust-lang.org/tools/install) (required for decode v0.3.5 onwards)

    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

Verify Rust Compiler 

    source "$HOME/.cargo/env" && echo "Rust version: $(rustc --version)" && echo "Cargo version: $(cargo --version)"

Set up pipx

    pipx ensurepath

Install TBC-Video-Export

    pipx install tbc-video-export

(There is also [self-contained builds](https://github.com/JuniorIsAJitterbug/tbc-video-export/releases) if install issues arise)

Optional dependencies for GPU (Nvidia Cards) FLAC compression support:

    sudo apt install make ocl-icd-opencl-dev mono-runtime

Also Requires FlaLDF [Download & Install via .deb for Linux](https://github.com/TokugawaHeavyIndustries/FlaLDF/releases/tag/v0.1b)


### NOTES!!

HiFi-Decode preview function - the python library sounddevice requires portaudio (libportaudio2 on Ubuntu). This is not included in the self-contained binaries and has to be installed locally if not already installed. (Included with most desktop environments.)


## Build and install VHS-Decode system-wide using pipx

The vhs-decode repository also has hifi-decode, cvbs-decode, ld-decode included.

Download VHS-Decode:

    git clone https://github.com/oyvindln/vhs-decode.git vhs-decode

Install VHS-Decode:

    cd vhs-decode

Build and install vhs-decode via pipx, using **one** of the below scripts.

### Base installation

    pipx install .

### With hifi-decode gui

    pipx install .[hifi_gui_qt6]

### With Intel specific cpu optimizations

    pipx install .[intel]

### If updating or reinstalling, you may need to add the `--force` flag to overwrite/update the previous installation.

    pipx install .[intel,hifi_gui_qt6] --force

Go back to the main directory with 

    cd .. 


## How to Update


To update your local repository enter `git pull` into the terminal while inside the vhs-decode directory, and then do `pipx install .[hifi_gui_qt6] --force`  - it will overwrite your previous installation and deploy the current version of the decoders.

## Usage


Note with WSL2 & Ubuntu, `./` in front of applications and scripts may be needed to run them or to run scripts within the folder.
### Decode Launcher (Qt6)

For a basic click-to-open launcher that lets you select common tools and open them in a terminal (or start native GUI tools), use:

    decode-launcher

or from source checkout:

    ./decode-launcher
You can drag and drop RF input files onto the launcher window or input field, and drop `.json` files to auto-fill the params JSON field.

Current native GUI launch targets include:

* `hifi-decode --gui`
* `filter-tune`

Use `cd vhs-decode` to enter into the directory to run commands, `cd ..` to go back a directory.

Use <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop the current process.

You don't actually type `<` and `>` on your input & output files.

# Build and install in a isolated python virtual environment

## Install all dependencies required by LD-Decode and VHS-Decode:
### Linux
  Ubuntu/debian based (debian 12/Ubuntu 24.04 or newer base required):

      sudo apt install git python3-dev pipx ffmpeg

  For Arch Linux:

      pacman -S base-devel git qt5-base qwt fftw ffmpeg pv cmake sox python python-pipx

  Install [Rust Compiler](https://www.rust-lang.org/tools/install) (required for decode v0.3.5 onwards)

      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

  Verify Rust Compiler 

      source "$HOME/.cargo/env" && echo "Rust version: $(rustc --version)" && echo "Cargo version: $(cargo --version)"
      
### Windows
  1. Install Python 3.13
   * Download the [python installer](https://www.python.org/downloads/)
   * **Make sure to check the box requesting Python be added to the PATH**
   * (NOTE: Due to the numba library that is used by vhs-decode taking some time to support the latest python version do not install a major version not supported by numba yet. Currently the latest supported version is 3.14. See the [numba repository](https://github.com/numba/numba/issues) if unsure.)
  1. Install Rust
   * Download the [Rust installer](https://www.rust-lang.org/tools/install) follow the wizard to install Rust
  1. Install Visual Studio Build Tools
   * Download the [Visual Studio Installer](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
   * In the installer, select `Visual Studio Build Tools 2022`
     * If there are multiple versions, select the latest year
   * Click on the `Desktop Development with C++` and a list of default components will be selected
   * Click `Install` to install them
  
## Create a virtual python environment

open a termial where you want to put the source code

    python -m venv vhs_decode_venv
    
    
## Enter the virtual environment
### windows (powershell)
    
    .\vhs_decode_venv\Scripts\Activate.ps1
        
### windows (cmd)

    .\vhs_decode_venv\Scripts\activate.bat
    
### linux/macos

    source ./vhs_decode_venv/bin/activate
    
### download source and build
    
    git clone https://github.com/oyvindln/vhs-decode.git vhs-decode
     
    python -m pip install .[hifi_gui_qt6]
    

you should now be able to run `vhs-decode`, `decode`, and `decode-launcher` , `hifi-decode --gui` etc

You have to re-enter the command under "enter the virtual environent" to enter the python virtual environment and be able to access vhs-decode when you start a new session.
     
     
# Using nix, needs full testing (Nix)

This project is built with [Nix](https://nixos.org/). The flake provides a reproducible build and generates the version file automatically.

## Requirements

- [Nix](https://nixos.org/) — a purely functional package manager that provides reproducible, declarative builds. Flakes must be enabled.

## Build

- Build the default package:
  - `nix build`

The build produces `./result` with the installed package and CLI tools.

## Run

- Run the main tool:
  - `nix run`
- Or run a specific tool:
  - `nix run .#ld-decode`
  - `nix run .#ld-ldf-reader-py`

## Development shell

- Enter a dev shell with dependencies:
  - `nix develop`

## Versioning

The flake generates a PEP 440 compliant version string and writes it to `lddecode/version` during the build. The CLI `--version` output comes from that file and includes git commit and dirty status when available.

## Documentation

The project documentation lives in `docs/` and is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/). All required dependencies (`mkdocs`, `mkdocs-material`, `mkdocs-awesome-nav`) are provided by the Nix dev shell.

- Enter the dev shell first (if not already inside one):
  - `nix develop`

- Start a live-reload preview server at `http://127.0.0.1:8000/`:
  - `mkdocs serve`

- Build a static site into `site/`:
  - `mkdocs build`

- Build the docs as a Nix package (output in `./result/`):
  - `nix build .#docs`

  
## Building tools (no longer hosted in this repo)

install dependencies (ubuntu-based)

    sudo apt install git qtbase5-dev libqwt-qt5-dev libfftw3-dev libavformat-dev libavcodec-dev libavutil-dev ffmpeg pv pkg-config make cmake sox pipx g++ python3-dev

    
Debian/Ubuntu does not have a qt6 version of qwt in repositories as of yet so you have to inform the build script to use Qt5 if both qt5 and qt6 are installed with `-DUSE_QT_VERSION=5` as it might otherwise try to compile with qt6 instead and failing to locate qwt. The option is otherwise not needed.


Compile and Install ld-tools suite:

    mkdir build2
    cd build2
    CXXFLAGS="-march=native" CFLAGS="-march=native" cmake .. -DCMAKE_BUILD_TYPE=Release -DUSE_QT_VERSION=5
    make -j4
    sudo make install
