# Linux installation

Linux installation is performed using appImage.  The pre-compiled installation package is here:

[ld-decode release](https://github.com/happycube/ld-decode/releases/latest){target="_blank"}

Download the appImage which will have a filename similar to ***ld-decode-dev-x86_64.AppImage***

This AppImage contains all required ld-decode tools:

- ld-decode
- ld-ldf-reader
- ld-ldf-reader-py
- ld-lds-reader

## Usage

Run ld-decode (default):

```
./ld-decode-*.AppImage [arguments]
```

Access other tools by adding them to your PATH:

```
./ld-decode-*.AppImage --appimage-extract
export PATH="$PWD/squashfs-root/usr/bin:$PATH"
ld-ldf-reader [arguments]
ld-ldf-reader-py [arguments]
ld-lds-reader [arguments]
```

Or create symlinks:

```
ln -s ld-decode-*.AppImage ld-ldf-reader
./ld-ldf-reader [arguments]
```