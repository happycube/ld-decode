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
        Datatypes/audio.cpp \
        Datatypes/f1frame.cpp \
        Datatypes/f2frame.cpp \
        Datatypes/f3frame.cpp \
        Datatypes/section.cpp \
        Datatypes/sector.cpp \
        Datatypes/tracktime.cpp \
        Decoders/c1circ.cpp \
        Decoders/c2circ.cpp \
        Decoders/c2deinterleave.cpp \
        Decoders/efmtof3frames.cpp \
        Decoders/f1toaudio.cpp \
        Decoders/f1todata.cpp \
        Decoders/f2tof1frames.cpp \
        Decoders/f3tof2frames.cpp \
        Decoders/syncf3frames.cpp \
        efmdecoder.cpp \
        efmprocess.cpp \
        main.cpp \
        ../library/tbc/logging.cpp

HEADERS += \
        Datatypes/audio.h \
        Datatypes/f1frame.h \
        Datatypes/f2frame.h \
        Datatypes/f3frame.h \
        Datatypes/section.h \
        Datatypes/sector.h \
        Datatypes/tracktime.h \
        Decoders/c1circ.h \
        Decoders/c2circ.h \
        Decoders/c2deinterleave.h \
        Decoders/efmtof3frames.h \
        Decoders/f1toaudio.h \
        Decoders/f1todata.h \
        Decoders/f2tof1frames.h \
        Decoders/f3tof2frames.h \
        Decoders/syncf3frames.h \
        efmdecoder.h \
        efmprocess.h \
        ezpwd/asserter \
        ezpwd/bch \
        ezpwd/bch_base \
        ezpwd/corrector \
        ezpwd/definitions \
        ezpwd/ezcod \
        ezpwd/output \
        ezpwd/rs \
        ezpwd/serialize \
        ezpwd/serialize_definitions \
        ezpwd/timeofday \
        ../library/tbc/logging.h

# Add external includes to the include path
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

DISTFILES += \
    ezpwd/rs_base
