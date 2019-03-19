QT -= gui

CONFIG += c++11 console
CONFIG -= app_bundle

# The following define makes your compiler emit warnings if you use
# any Qt feature that has been marked deprecated (the exact warnings
# depend on your compiler). Please consult the documentation of the
# deprecated API in order to know how to port your code away from it.
DEFINES += QT_DEPRECATED_WARNINGS

# You can also make your code fail to compile if it uses deprecated APIs.
# In order to do so, uncomment the following line.
# You can also select to disable deprecated APIs only up to a certain version of Qt.
#DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

SOURCES += \
        main.cpp \
    efmprocess.cpp \
    f3frame.cpp \
    efmtof3frames.cpp \
    c1circ.cpp \
    c2circ.cpp \
    c2deinterleave.cpp \
    tracktime.cpp \
    f2frame.cpp \
    f3tof2frames.cpp \
    f2framestoaudio.cpp \
    f3tosections.cpp \
    section.cpp \
    f1frame.cpp \
    f2tof1frames.cpp \
    sector.cpp \
    sectorstodata.cpp

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /usr/local/bin/
!isEmpty(target.path): INSTALLS += target

HEADERS += \
    efmprocess.h \
    f3frame.h \
    efmtof3frames.h \
    ezpwd/asserter \
    ezpwd/bch \
    ezpwd/bch_base \
    ezpwd/corrector \
    ezpwd/definitions \
    ezpwd/ezcod \
    ezpwd/output \
    ezpwd/rs \
    ezpwd/rs_base \
    ezpwd/serialize \
    ezpwd/serialize_definitions \
    ezpwd/timeofday \
    c1circ.h \
    c2circ.h \
    c2deinterleave.h \
    tracktime.h \
    f2frame.h \
    f3tof2frames.h \
    f2framestoaudio.h \
    f3tosections.h \
    section.h \
    f1frame.h \
    f2tof1frames.h \
    sector.h \
    sectorstodata.h

