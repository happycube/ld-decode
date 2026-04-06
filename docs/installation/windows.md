# Windows Installation

Windows installation is performed using a portable ZIP archive. The pre-compiled installation package is here:

[ld-decode release](https://github.com/happycube/ld-decode/releases/latest){target="_blank"}

Download the ZIP file which will have a filename similar to ***ld-decode-dev-windows.zip***

This archive contains all required ld-decode tools:

- ld-decode
- ld-ldf-reader-py

## Installation

1. Download the ZIP file
2. Extract the contents to a location of your choice (e.g., `C:\ld-decode`)
3. The installation is portable - no installation wizard or registry entries required

## Usage

Run ld-decode from Command Prompt or PowerShell:

```
C:\path\to\ld-decode\ld-decode.exe [arguments]
```

For easier access, add the ld-decode directory to your PATH:

**Command Prompt:**
```
set PATH=%PATH%;C:\path\to\ld-decode
ld-decode [arguments]
```

**PowerShell:**
```
$env:Path += ";C:\path\to\ld-decode"
ld-decode [arguments]
```

To permanently add to PATH, edit your system environment variables through System Properties.
