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

#ld-chroma-decoder HEADERS
set(HEADERS
    decoder.h
    decoderpool.h
    monodecoder.h
    ntscdecoder.h
    paldecoder.h
)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

# ld-chroma-decoder executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core fftw3 ld-library ld-chroma-lib)

install(TARGETS ${PROJECT_NAME})

#install(TARGETS ld-chroma-lib LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR} ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
