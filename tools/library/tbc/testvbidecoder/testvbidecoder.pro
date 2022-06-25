CONFIG += c++17 testcase
CONFIG -= app_bundle

SOURCES += \
    testvbidecoder.cpp \
    ../vbidecoder.cpp

HEADERS += \
    ../vbidecoder.h

INCLUDEPATH += \
    ..

target.CONFIG += no_default_install
