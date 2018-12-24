#-------------------------------------------------
#
# Project created by QtCreator 2018-11-01T08:54:18
#
#-------------------------------------------------

QT       -= gui

TARGET = ld-decode-shared
TEMPLATE = lib

DEFINES += LDDECODESHARED_LIBRARY

# The following define makes your compiler emit warnings if you use
# any feature of Qt which has been marked as deprecated (the exact warnings
# depend on your compiler). Please consult the documentation of the
# deprecated API in order to know how to port your code away from it.
DEFINES += QT_DEPRECATED_WARNINGS

# You can also make your code fail to compile if you use deprecated APIs.
# In order to do so, uncomment the following line.
# You can also select to disable deprecated APIs only up to a certain version of Qt.
#DEFINES += QT_DISABLE_DEPRECATED_BEFORE=0x060000    # disables all the APIs deprecated before Qt 6.0.0

SOURCES += \
    sourcevideo.cpp \
    lddecodemetadata.cpp \
    sourcefield.cpp

HEADERS += \
        ld-decode-shared_global.h \ 
    sourcevideo.h \
    lddecodemetadata.h \
    sourcefield.h

unix {
    target.path = /usr/lib
    INSTALLS += target
}

# Set the destination directory of the shared libraries
MYDLLDIR = $$IN_PWD/../library

# Move all of the project's header files to the same directory
DESTDIR = \"$$MYDLLDIR\"
DDIR = \"$$MYDLLDIR/\"
SDIR = \"$$IN_PWD/\"
# Replace slashes in paths with backslashes for Windows
win32:file ~= s,/,\\,g
win32:DDIR ~= s,/,\\,g
win32:SDIR ~= s,/,\\,g
# For-loop to copy all header files to DDIR.
for(file, HEADERS) {
    QMAKE_POST_LINK += $$QMAKE_COPY $$quote($${SDIR}$${file}) $$quote($$DDIR) $$escape_expand(\\n\\t)
}
