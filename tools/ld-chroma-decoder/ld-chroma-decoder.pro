QT -= gui

CONFIG += c++11 console
CONFIG -= app_bundle

# The following define makes your compiler emit warnings if you use
# any feature of Qt which as been marked deprecated (the exact warnings
# depend on your compiler). Please consult the documentation of the
# deprecated API in order to know how to port your code away from it.
DEFINES += QT_DEPRECATED_WARNINGS

# You can also make your code fail to compile if you use deprecated APIs.
# In order to do so, uncomment the following line.
# You can also select to disable deprecated APIs only up to a certain version of Qt.
#DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

SOURCES += \
    comb.cpp \
    decoder.cpp \
    decoderpool.cpp \
    framecanvas.cpp \
    main.cpp \
    monodecoder.cpp \
    ntscdecoder.cpp \
    palcolour.cpp \
    paldecoder.cpp \
    rgb.cpp \
    ycbcr.cpp \
    sourcefield.cpp \
    transformpal.cpp \
    transformpal2d.cpp \
    transformpal3d.cpp \
    ../library/tbc/lddecodemetadata.cpp \
    ../library/tbc/sourcevideo.cpp \
    ../library/tbc/vbidecoder.cpp \
    ../library/tbc/logging.cpp \
    ../library/tbc/dropouts.cpp

HEADERS += \
    comb.h \
    decoder.h \
    decoderpool.h \
    framecanvas.h \
    monodecoder.h \
    ntscdecoder.h \
    outputframe.h \
    palcolour.h \
    paldecoder.h \
    rgb.h \
    sourcefield.h \
    transformpal.h \
    transformpal2d.h \
    transformpal3d.h \
    ycbcr.h \
    yiq.h \
    ../library/filter/deemp.h \
    ../library/filter/firfilter.h \
    ../library/filter/iirfilter.h \
    ../library/tbc/lddecodemetadata.h \
    ../library/tbc/sourcevideo.h \
    ../library/tbc/vbidecoder.h \
    ../library/tbc/logging.h \
    ../library/tbc/dropouts.h

# Add external includes to the include path
INCLUDEPATH += ../library/filter
INCLUDEPATH += ../library/tbc

# Include git information definitions
isEmpty(BRANCH) {
    BRANCH = "unknown"
}
isEmpty(COMMIT) {
    COMMIT = "unknown"
}
DEFINES += APP_BRANCH=\"\\\"$${BRANCH}\\\"\" \
    APP_COMMIT=\"\\\"$${COMMIT}\\\"\"


# Rules for installation
isEmpty(PREFIX) {
    PREFIX = /usr/local
}
unix:!android: target.path = $$PREFIX/bin/
!isEmpty(target.path): INSTALLS += target

# Additional include paths to support MacOS compilation
macx {
INCLUDEPATH += "/usr/local/include"
}

# Normal open-source OS goodness
LIBS += -L"/usr/local/lib"
LIBS += -lfftw3
