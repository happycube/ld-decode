CONFIG += c++17 testcase
CONFIG -= app_bundle

SOURCES += \
    testmetadata.cpp \
    ../dropouts.cpp \
    ../jsonio.cpp \
    ../lddecodemetadata.cpp \
    ../vbidecoder.cpp

HEADERS += \
    ../dropouts.h \
    ../jsonio.h \
    ../lddecodemetadata.h \
    ../vbidecoder.h

INCLUDEPATH += \
    ..

target.CONFIG += no_default_install
