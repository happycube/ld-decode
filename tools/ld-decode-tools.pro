# Top level project file for ld-decode-tools

TEMPLATE = subdirs
SUBDIRS = \
    ld-analyse \
    ld-chroma-decoder \
    ld-chroma-decoder/encoder \
    ld-discmap \
    ld-dropout-correct \
    ld-export-metadata \
    ld-lds-converter \
    ld-process-efm \
    ld-process-vbi \
    ld-disc-stacker \
    ld-process-vits \
    library/filter/testfilter \
    library/tbc/testlinenumber \
    library/tbc/testmetadata \
    library/tbc/testvbidecoder
