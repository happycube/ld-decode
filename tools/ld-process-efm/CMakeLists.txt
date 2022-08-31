message(STATUS "---------Beginning cmake build of ld-process-efm ---------")
project(ld-process-efm)

#ld-process-efm SOURCES
set(SOURCES
    efmprocess.cpp
    main.cpp
    Datatypes/audio.cpp
    Datatypes/f1frame.cpp
    Datatypes/f2frame.cpp
    Datatypes/f3frame.cpp
    Datatypes/section.cpp
    Datatypes/sector.cpp
    Datatypes/tracktime.cpp
    Decoders/c1circ.cpp
    Decoders/c2circ.cpp
    Decoders/c2deinterleave.cpp
    Decoders/efmtof3frames.cpp
    Decoders/f1toaudio.cpp
    Decoders/f1todata.cpp
    Decoders/f2tof1frames.cpp
    Decoders/f3tof2frames.cpp
    Decoders/syncf3frames.cpp
    ../library/tbc/logging.cpp
)

#ld-process-efm HEADERS
set(HEADERS
    efmprocess.h
    Datatypes/audio.h
    Datatypes/f1frame.h
    Datatypes/f2frame.h
    Datatypes/f3frame.h
    Datatypes/section.h
    Datatypes/sector.h
    Datatypes/tracktime.h
    Decoders/c1circ.h
    Decoders/c2circ.h
    Decoders/c2deinterleave.h
    Decoders/efmtof3frames.h
    Decoders/f1toaudio.h
    Decoders/f1todata.h
    Decoders/f2tof1frames.h
    Decoders/f3tof2frames.h
    Decoders/syncf3frames.h
    ezpwd/asserter
    ezpwd/bch
    ezpwd/bch_base
    ezpwd/corrector
    ezpwd/definitions
    ezpwd/ezcod
    ezpwd/output
    ezpwd/rs
    ezpwd/serialize
    ezpwd/serialize_definitions
    ezpwd/timeofday
    ../library/tbc/logging.h
)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

# ld-process-efm executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Widgets ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
