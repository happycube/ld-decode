message(STATUS "---------Beginning cmake build of ld-chroma-decoder---------")
project(ld-chroma-decoder)

add_library(ld-chroma-lib STATIC
    comb.cpp
    componentframe.cpp
    framecanvas.cpp
    outputwriter.cpp
    palcolour.cpp
    sourcefield.cpp
    transformpal.cpp
    transformpal2d.cpp
    transformpal3d.cpp
)

target_include_directories(ld-chroma-lib PUBLIC .)

target_link_libraries(ld-chroma-lib PRIVATE Qt::Core fftw3 ld-library)

#ld-chroma-decoder SOURCES
set(SOURCES
    decoder.cpp
    decoderpool.cpp
    main.cpp
    monodecoder.cpp
    ntscdecoder.cpp
    paldecoder.cpp
)

# ld-chroma-decoder executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core fftw3 ld-library ld-chroma-lib)

install(TARGETS ${PROJECT_NAME})
