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
        Datatypes/f1frame.cpp \
        Datatypes/f2frame.cpp \
        Datatypes/f3frame.cpp \
        Datatypes/section.cpp \
        Datatypes/sector.cpp \
        Datatypes/tracktime.cpp \
        Decoder/c1circ.cpp \
        Decoder/c2circ.cpp \
        Decoder/c2deinterleave.cpp \
        Decoder/efmtof3frames.cpp \
        Decoder/f1tosectors.cpp \
        Decoder/f2framestoaudio.cpp \
        Decoder/f2tof1frames.cpp \
        Decoder/f3tof2frames.cpp \
        Decoder/f3tosections.cpp \
        Decoder/sectiontometa.cpp \
        Decoder/sectorstodata.cpp \
        Decoder/sectorstometa.cpp \
        aboutdialog.cpp \
        configuration.cpp \
        efmprocess.cpp \
        logging.cpp \
        main.cpp \
        mainwindow.cpp

HEADERS += \
        Datatypes/f1frame.h \
        Datatypes/f2frame.h \
        Datatypes/f3frame.h \
        Datatypes/section.h \
        Datatypes/sector.h \
        Datatypes/tracktime.h \
        Decoder/c1circ.h \
        Decoder/c2circ.h \
        Decoder/c2deinterleave.h \
        Decoder/efmtof3frames.h \
        Decoder/f1tosectors.h \
        Decoder/f2framestoaudio.h \
        Decoder/f2tof1frames.h \
        Decoder/f3tof2frames.h \
        Decoder/f3tosections.h \
        Decoder/sectiontometa.h \
        Decoder/sectorstodata.h \
        Decoder/sectorstometa.h \
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
    Decoder/ezpwd/rs_base \
    ezpwd/rs_base
