CONFIG += c++11 testcase
CONFIG -= app_bundle

SOURCES += \
    testmetadata.cpp \
    ../dropouts.cpp \
    ../lddecodemetadata.cpp \
    ../vbidecoder.cpp

HEADERS += \
    ../dropouts.h \
    ../lddecodemetadata.h \
    ../vbidecoder.h

INCLUDEPATH += \
    ..

target.CONFIG += no_default_install
