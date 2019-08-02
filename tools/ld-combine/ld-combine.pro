#-------------------------------------------------
#
# Project created by QtCreator 2019-08-02T08:13:33
#
#-------------------------------------------------

QT       += core gui

greaterThan(QT_MAJOR_VERSION, 4): QT += widgets

TARGET = ld-combine
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
        ../library/tbc/lddecodemetadata.cpp \
        ../library/tbc/sourcevideo.cpp \
        aboutdialog.cpp \
        configuration.cpp \
        logging.cpp \
        main.cpp \
        mainwindow.cpp \
        tbcsources.cpp

HEADERS += \
        ../library/tbc/lddecodemetadata.h \
        ../library/tbc/sourcevideo.h \
        aboutdialog.h \
        configuration.h \
        logging.h \
        mainwindow.h \
        tbcsources.h

FORMS += \
        aboutdialog.ui \
        mainwindow.ui

# Add external includes to the include path
INCLUDEPATH += ../library/tbc

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /usr/local/bin/
!isEmpty(target.path): INSTALLS += target
