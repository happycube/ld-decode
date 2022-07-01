CONFIG += c++17 testcase
CONFIG -= app_bundle

SOURCES += \
    testfilter.cpp

HEADERS += \
    ../deemp.h \
    ../firfilter.h \
    ../iirfilter.h

INCLUDEPATH += \
    ..

target.CONFIG += no_default_install
