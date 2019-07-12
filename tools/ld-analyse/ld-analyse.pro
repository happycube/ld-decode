#-------------------------------------------------
#
# Project created by QtCreator 2018-11-03T13:40:24
#
#-------------------------------------------------

QT       += core gui charts

greaterThan(QT_MAJOR_VERSION, 4): QT += widgets

TARGET = ld-analyse
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
    busydialog.cpp \
        main.cpp \
        mainwindow.cpp \
    oscilloscopedialog.cpp \
    aboutdialog.cpp \
    snranalysisdialog.cpp \
    vbidialog.cpp \
    configuration.cpp \
    ntscdialog.cpp \
    ../ld-chroma-decoder/palcolour.cpp \
    ../ld-chroma-decoder/comb.cpp \
    ../ld-chroma-decoder/rgb.cpp \
    ../ld-chroma-decoder/yiq.cpp \
    videometadatadialog.cpp \
    frameqlabel.cpp \
    dropoutanalysisdialog.cpp \
    ../ld-chroma-decoder/opticalflow.cpp \
    vitsmetricsdialog.cpp

HEADERS += \
    busydialog.h \
        mainwindow.h \
    oscilloscopedialog.h \
    aboutdialog.h \
    snranalysisdialog.h \
    vbidialog.h \
    configuration.h \
    ntscdialog.h \
    ../ld-chroma-decoder/palcolour.h \
    ../ld-chroma-decoder/comb.h \
    ../ld-chroma-decoder/rgb.h \
    ../ld-chroma-decoder/yiq.h \
    videometadatadialog.h \
    frameqlabel.h \
    dropoutanalysisdialog.h \
    ../ld-chroma-decoder/yiqbuffer.h \
    ../ld-chroma-decoder/opticalflow.h \
    vitsmetricsdialog.h

FORMS += \
    busydialog.ui \
        mainwindow.ui \
    oscilloscopedialog.ui \
    aboutdialog.ui \
    snranalysisdialog.ui \
    vbidialog.ui \
    ntscdialog.ui \
    videometadatadialog.ui \
    dropoutanalysisdialog.ui \
    vitsmetricsdialog.ui

MYDLLDIR = $$IN_PWD/../library

# As our header files are in the same directory, we can make Qt Creator find it
# by specifying it as INCLUDEPATH.
INCLUDEPATH += $$MYDLLDIR
INCLUDEPATH += ../ld-chroma-decoder

# Dependency to library domain (libdomain.so for Unices or domain.dll on Win32)
# Repeat this for more libraries if needed.
win32:LIBS += $$quote($$MYDLLDIR/ld-decode-shared.dll)
 unix:LIBS += $$quote(-L$$MYDLLDIR) -lld-decode-shared

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /usr/local/bin/
!isEmpty(target.path): INSTALLS += target

RESOURCES += \
    ld-analyse-resources.qrc

# Additional include paths to support MacOS compilation
INCLUDEPATH += "/usr/local/opt/opencv@2/include"
LIBS += -L"/usr/local/opt/opencv@2/lib"

# Normal open-source OS goodness
INCLUDEPATH += "/usr/local/include/opencv"
LIBS += -L"/usr/local/lib"
LIBS += -lopencv_core -lopencv_imgcodecs -lopencv_highgui -lopencv_imgproc -lopencv_video



