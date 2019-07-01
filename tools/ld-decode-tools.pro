TEMPLATE = subdirs
SUBDIRS = \
    ld-analyse \
    ld-chroma-decoder \
    ld-chroma-decoder/testfilter \
    ld-combine \
    ld-decode-shared \
    ld-dropout-correct \
    ld-lds-converter \
    ld-ldstoefm \
    ld-process-efm \
    ld-process-efm-rev5 \
    ld-process-vbi

ld-analyse.depends = ld-decode-shared
ld-chroma-decoder.depends = ld-decode-shared
ld-combine.depends = ld-decode-shared
ld-dropout-correct.depends = ld-decode-shared
ld-process-vbi.depends = ld-decode-shared
