CONFIG += c++11 testcase
CONFIG -= app_bundle

SOURCES += \
    testfilter.cpp

HEADERS += \
    ../firfilter.h \
    ../iirfilter.h \
    ../../../../deemp.h

INCLUDEPATH += \
    .. \
    ../../../..
