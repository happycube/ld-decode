<img src="https://github.com/oyvindln/vhs-decode/wiki/assets/icons/Cross-Platform-VHS-Decode-Trasparent.png" width="300" height="">


# [VHS-Decode](https://github.com/oyvindln/vhs-decode) and ld-decode (python parts)

A software decoder for analog videotape, a fork of [LD-Decode](https://github.com/happycube/ld-decode), the decoding software powering the [Domesday86 Project](https://www.domesday86.com/).

This version has been modified to work with the differences found in FM RF signals taken directly from colour-under & composite FM modulated videotape formats, captured directly from the heads pre-amplification & tracking stage before any internal video/hifi processing.

The package hosted on pypi contains the python parts of vhs-decode and ld-decode - that is the vhs-deocde, ld-decode and cvbs-decode executables, but not the other parts. Can be used in conjunction with e.g appimage download on linux or binary downloads on windows instead of building from source. See the [website](https://github.com/oyvindln/vhs-decode)) for the full readme. (note that ld-decode depends on the ld-ac3-decode and sox binaries being in path for ac3 support which are currently not included automatically when installing this package.)
