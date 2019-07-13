# Top level project file for ld-decode-tools
# ld-decode-shared must be built first.

TEMPLATE = subdirs
SUBDIRS = \
    ld-decode-shared \
    ld-analyse \
    ld-chroma-decoder \
    ld-chroma-decoder/testfilter \
    ld-combine \
    ld-dropout-correct \
    ld-lds-converter \
    ld-ldstoefm \
    ld-process-efm \
    ld-process-vbi

ld-analyse.depends = ld-decode-shared
ld-chroma-decoder.depends = ld-decode-shared
ld-combine.depends = ld-decode-shared
ld-dropout-correct.depends = ld-decode-shared
ld-process-vbi.depends = ld-decode-shared
