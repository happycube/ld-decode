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
    main.cpp \
    decoder.cpp \
    decoderpool.cpp \
    palcolour.cpp \
    paldecoder.cpp \
    comb.cpp \
    rgb.cpp \
    yiq.cpp \
    ntscdecoder.cpp \
    opticalflow.cpp \
    ../library/tbc/lddecodemetadata.cpp \
    ../library/tbc/sourcevideo.cpp

HEADERS += \
    decoder.h \
    decoderpool.h \
    palcolour.h \
    paldecoder.h \
    comb.h \
    rgb.h \
    yiq.h \
    iirfilter.h \
    ntscdecoder.h \
    ../../deemp.h \
    opticalflow.h \
    yiqbuffer.h \
    ../library/tbc/lddecodemetadata.h \
    ../library/tbc/sourcevideo.h

# Add external includes to the include path
INCLUDEPATH += ../library/tbc

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /usr/local/bin/
!isEmpty(target.path): INSTALLS += target

# Additional include paths to support MacOS compilation
INCLUDEPATH += "/usr/local/opt/opencv@2/include"
LIBS += -L"/usr/local/opt/opencv@2/lib"

# Normal open-source OS goodness
INCLUDEPATH += "/usr/local/include/opencv"
LIBS += -L"/usr/local/lib"
LIBS += -lopencv_core -lopencv_imgproc -lopencv_video
