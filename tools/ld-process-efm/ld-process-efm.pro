#-------------------------------------------------
#
# Project created by QtCreator 2019-06-29T06:07:37
#
#-------------------------------------------------

QT       += core gui

greaterThan(QT_MAJOR_VERSION, 4): QT += widgets

TARGET = ld-process-efm
TEMPLATE = app

# The following define makes your compiler emit warnings if you use
# any feature of Qt which has been marked as deprecated (the exact warnings
# depend on your compiler). Please consult the documentation of the
# deprecated API in order to know how to port your code away from it.
DEFINES += QT_DEPRECATED_WARNINGS

# You can also make your code fail to compile if you use deprecated APIs.
# In order to do so, uncomment the following line.
# You can also select to disable deprecated APIs only up to a certain version of Qt.
#DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

CONFIG += c++11

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
        aboutdialog.cpp \
        configuration.cpp \
        efmprocess.cpp \
        main.cpp \
        mainwindow.cpp \
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
        aboutdialog.h \
        configuration.h \
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
        mainwindow.h \
        ../library/tbc/logging.h

FORMS += \
        aboutdialog.ui \
        mainwindow.ui

# Add external includes to the include path
INCLUDEPATH += ../library/tbc

# Rules for installation
isEmpty(PREFIX) {
    PREFIX = /usr/local
}
unix:!android: target.path = $$PREFIX/bin/
!isEmpty(target.path): INSTALLS += target

RESOURCES += \
    applicationicons.qrc
    
ICON = Graphics/ld-process-efm.icns

DISTFILES += \
    ezpwd/rs_base
