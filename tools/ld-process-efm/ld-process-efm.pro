#-------------------------------------------------
#
# Project created by QtCreator 2019-06-06T19:32:31
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
        Decoder/c1circ.cpp \
        Decoder/c2circ.cpp \
        Decoder/c2deinterleave.cpp \
        Decoder/efmtof3frames.cpp \
        Decoder/f1frame.cpp \
        Decoder/f1tosectors.cpp \
        Decoder/f2frame.cpp \
        Decoder/f2framestoaudio.cpp \
        Decoder/f2tof1frames.cpp \
        Decoder/f3frame.cpp \
        Decoder/f3tof2frames.cpp \
        Decoder/f3tosections.cpp \
        Decoder/section.cpp \
        Decoder/sectiontometa.cpp \
        Decoder/sector.cpp \
        Decoder/sectorstodata.cpp \
        Decoder/sectorstometa.cpp \
        Decoder/tracktime.cpp \
        aboutdialog.cpp \
        configuration.cpp \
        efmprocess.cpp \
        logging.cpp \
        main.cpp \
        mainwindow.cpp

HEADERS += \
        Decoder/JsonWax/JsonWax.h \
        Decoder/JsonWax/JsonWaxEditor.h \
        Decoder/JsonWax/JsonWaxParser.h \
        Decoder/JsonWax/JsonWaxSerializer.h \
        Decoder/c1circ.h \
        Decoder/c2circ.h \
        Decoder/c2deinterleave.h \
        Decoder/efmtof3frames.h \
        Decoder/ezpwd/asserter \
        Decoder/ezpwd/bch \
        Decoder/ezpwd/bch_base \
        Decoder/ezpwd/corrector \
        Decoder/ezpwd/definitions \
        Decoder/ezpwd/ezcod \
        Decoder/ezpwd/output \
        Decoder/ezpwd/rs \
        Decoder/ezpwd/serialize \
        Decoder/ezpwd/serialize_definitions \
        Decoder/ezpwd/timeofday \
        Decoder/f1frame.h \
        Decoder/f1tosectors.h \
        Decoder/f2frame.h \
        Decoder/f2framestoaudio.h \
        Decoder/f2tof1frames.h \
        Decoder/f3frame.h \
        Decoder/f3tof2frames.h \
        Decoder/f3tosections.h \
        Decoder/section.h \
        Decoder/sectiontometa.h \
        Decoder/sector.h \
        Decoder/sectorstodata.h \
        Decoder/sectorstometa.h \
        Decoder/tracktime.h \
        aboutdialog.h \
        configuration.h \
        efmprocess.h \
        logging.h \
        mainwindow.h

FORMS += \
        aboutdialog.ui \
        mainwindow.ui

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /usr/local/bin/
!isEmpty(target.path): INSTALLS += target

RESOURCES += \
    resources.qrc

DISTFILES += \
    Decoder/JsonWax/LICENSE \
    Decoder/JsonWax/README.md \
    Decoder/ezpwd/rs_base
