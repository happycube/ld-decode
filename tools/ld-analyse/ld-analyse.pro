#-------------------------------------------------
#
# Project created by QtCreator 2018-11-03T13:40:24
#
#-------------------------------------------------

QT       += core gui

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
    closedcaptionsdialog.cpp \
    main.cpp \
    mainwindow.cpp \
    oscilloscopedialog.cpp \
    aboutdialog.cpp \
    palchromadecoderconfigdialog.cpp \
    snranalysisdialog.cpp \
    tbcsource.cpp \
    vbidialog.cpp \
    configuration.cpp \
    dropoutanalysisdialog.cpp \
    ../ld-chroma-decoder/palcolour.cpp \
    ../ld-chroma-decoder/comb.cpp \
    ../ld-chroma-decoder/rgb.cpp \
    ../ld-chroma-decoder/yiq.cpp \
    ../ld-chroma-decoder/transformpal.cpp \
    ../ld-chroma-decoder/transformpal2d.cpp \
    ../ld-chroma-decoder/transformpal3d.cpp \
    ../ld-chroma-decoder/framecanvas.cpp \
    ../ld-chroma-decoder/opticalflow.cpp \
    ../ld-chroma-decoder/sourcefield.cpp \
    ../library/tbc/lddecodemetadata.cpp \
    ../library/tbc/sourcevideo.cpp \
    ../library/tbc/vbidecoder.cpp \
    ../library/tbc/filters.cpp

HEADERS += \
    busydialog.h \
    closedcaptionsdialog.h \
    mainwindow.h \
    oscilloscopedialog.h \
    aboutdialog.h \
    palchromadecoderconfigdialog.h \
    snranalysisdialog.h \
    tbcsource.h \
    vbidialog.h \
    configuration.h \
    dropoutanalysisdialog.h \
    ../ld-chroma-decoder/palcolour.h \
    ../ld-chroma-decoder/comb.h \
    ../ld-chroma-decoder/rgb.h \
    ../ld-chroma-decoder/yiq.h \
    ../ld-chroma-decoder/transformpal.h \
    ../ld-chroma-decoder/transformpal2d.h \
    ../ld-chroma-decoder/transformpal3d.h \
    ../ld-chroma-decoder/framecanvas.h \
    ../ld-chroma-decoder/yiqbuffer.h \
    ../ld-chroma-decoder/opticalflow.h \
    ../ld-chroma-decoder/sourcefield.h \
    ../library/filter/firfilter.h \
    ../library/tbc/lddecodemetadata.h \
    ../library/tbc/sourcevideo.h \
    ../library/tbc/vbidecoder.h \
    ../library/tbc/filters.h

FORMS += \
    busydialog.ui \
    closedcaptionsdialog.ui \
    mainwindow.ui \
    oscilloscopedialog.ui \
    aboutdialog.ui \
    palchromadecoderconfigdialog.ui \
    snranalysisdialog.ui \
    vbidialog.ui \
    dropoutanalysisdialog.ui

# Add external includes to the include path
INCLUDEPATH += ../library/filter
INCLUDEPATH += ../library/tbc
INCLUDEPATH += ../ld-chroma-decoder

# Rules for installation
isEmpty(PREFIX) {
    PREFIX = /usr/local
}
unix:!android: target.path = $$PREFIX/bin/
!isEmpty(target.path): INSTALLS += target

RESOURCES += \
    ld-analyse-resources.qrc

# Additional include paths to support MacOS compilation
INCLUDEPATH += "/usr/local/opt/opencv@2/include"
LIBS += -L"/usr/local/opt/opencv@2/lib"

# Normal open-source OS goodness
INCLUDEPATH += "/usr/local/include/opencv"
LIBS += -L"/usr/local/lib"
LIBS += -lopencv_core -lopencv_imgcodecs -lopencv_highgui -lopencv_imgproc -lopencv_video -lfftw3

# Include the QWT library (used for charting)
INCLUDEPATH += $(QWT)/include
LIBS += -lqwt-qt5




