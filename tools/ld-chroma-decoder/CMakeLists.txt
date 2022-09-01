# Library for chroma decoders

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

# ld-chroma-decoder

add_executable(ld-chroma-decoder
    decoder.cpp
    decoderpool.cpp
    main.cpp
    monodecoder.cpp
    ntscdecoder.cpp
    paldecoder.cpp
)

target_link_libraries(ld-chroma-decoder PRIVATE Qt::Core fftw3 ld-library ld-chroma-lib)

install(TARGETS ld-chroma-decoder)
