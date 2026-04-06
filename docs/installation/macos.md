# MacOS Installation

macOS installation is performed using a DMG disk image. The pre-compiled installation package is here:

[ld-decode release](https://github.com/happycube/ld-decode/releases/latest){target="_blank"}

Download the DMG which will have a filename similar to ***ld-decode-dev-macOS.dmg***

This package contains all required ld-decode tools:

- ld-decode
- ld-ldf-reader-py

## Installation

1. Download the DMG file
2. Open the DMG file
3. Drag the application to your Applications folder or desired location
4. **Important:** Since the DMG is self-signed, macOS will block it from running initially

### Granting Permission to Run

When you first try to run the application, macOS will show a security warning. To allow it:

1. Go to **System Preferences** > **Security & Privacy**
2. Click the **General** tab
3. You should see a message about the blocked application
4. Click **Open Anyway**

Alternatively, you can right-click (or Control-click) the application and select **Open**, then confirm in the dialog.

## Usage

Run ld-decode from the terminal:

```
/path/to/ld-decode [arguments]
```

Or add the tools to your PATH:

```
export PATH="/path/to/ld-decode/bin:$PATH"
ld-decode [arguments]
ld-ldf-reader-py [arguments]
```
