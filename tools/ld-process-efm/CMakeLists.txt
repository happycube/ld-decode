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
)

# ld-process-efm executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
