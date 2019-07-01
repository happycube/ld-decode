TEMPLATE = subdirs
SUBDIRS = \
    ld-analyse \
    ld-comb-ntsc \
    ld-comb-ntsc/testfilter \
    ld-comb-pal \
    ld-combine \
    ld-decode-shared \
    ld-dropout-correct \
    ld-lds-converter \
    ld-ldstoefm \
    ld-process-efm \
    ld-process-efm-rev5 \
    ld-process-vbi

ld-analyse.depends = ld-decode-shared
ld-comb-ntsc.depends = ld-decode-shared
ld-comb-pal.depends = ld-decode-shared
ld-combine.depends = ld-decode-shared
ld-dropout-correct.depends = ld-decode-shared
ld-process-vbi.depends = ld-decode-shared
