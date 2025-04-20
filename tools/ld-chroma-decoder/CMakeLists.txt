# Library for chroma decoders

# For M_PI constant
add_compile_definitions(_USE_MATH_DEFINES)

add_library(lddecode-chroma STATIC
	decoder.cpp
	decoderpool.cpp
    comb.cpp
    componentframe.cpp
    framecanvas.cpp
    outputwriter.cpp
    palcolour.cpp
    sourcefield.cpp
    transformpal.cpp
    transformpal2d.cpp
    transformpal3d.cpp
	monodecoder.cpp
)

target_include_directories(lddecode-chroma PUBLIC .)

target_link_libraries(lddecode-chroma PRIVATE Qt::Core ${FFTW_LIBRARY} lddecode-library)

target_include_directories(lddecode-chroma PRIVATE ${FFTW_INCLUDE_DIR})

# ld-chroma-decoder

add_executable(ld-chroma-decoder
    decoder.cpp
    decoderpool.cpp
    main.cpp
    monodecoder.cpp
    ntscdecoder.cpp
    paldecoder.cpp
)

set_target_properties(lddecode-chroma PROPERTIES AUTOMOC ON)

target_include_directories(ld-chroma-decoder PRIVATE ${FFTW_INCLUDE_DIR})

target_link_libraries(ld-chroma-decoder PRIVATE Qt::Core lddecode-library lddecode-chroma)

install(TARGETS ld-chroma-decoder)
