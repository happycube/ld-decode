QT -= gui

CONFIG += c++11 console
CONFIG -= app_bundle

# Set the compiler optimisation
# remove possible other optimization flags
QMAKE_CXXFLAGS_RELEASE -= -O
QMAKE_CXXFLAGS_RELEASE -= -O1
QMAKE_CXXFLAGS_RELEASE -= -O2

# add the desired -O3 if not present
QMAKE_CXXFLAGS_RELEASE *= -O3

# The following define makes your compiler emit warnings if you use
# any feature of Qt which as been marked deprecated (the exact warnings
# depend on your compiler). Please consult the documentation of the
# deprecated API in order to know how to port your code away from it.
DEFINES += QT_DEPRECATED_WARNINGS

# You can also make your code fail to compile if you use deprecated APIs.
# In order to do so, uncomment the following line.
# You can also select to disable deprecated APIs only up to a certain version of Qt.
#DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

# Override the target directory for a release build
Release:DESTDIR = ../../
release:DESTDIR = ../../

SOURCES += main.cpp \
    tbcpal.cpp \
    filter.cpp \
    tbc.cpp \
    interpretvbi.cpp

HEADERS += \
    tbcpal.h \
    filter.h \
    ../../deemp.h \
    deemp2.h \
    tbc.h \
    interpretvbi.h
