cmake_minimum_required(VERSION 3.16)

project(ld-process-efm)

find_package(Qt6 REQUIRED COMPONENTS Core)

add_executable(ld-process-efm
    efmprocess.cpp
    main.cpp
    ../../tools/library/tbc/logging.cpp
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

target_include_directories(ld-process-efm PRIVATE . ../../tools/library/tbc ../../tools/efm-decoder/libs/ezpwd/c++)

# Define application version info
target_compile_definitions(ld-process-efm PRIVATE 
    APP_BRANCH="prototypes"
    APP_COMMIT="unknown"
)

target_link_libraries(ld-process-efm PRIVATE Qt6::Core)

install(TARGETS ld-process-efm)
