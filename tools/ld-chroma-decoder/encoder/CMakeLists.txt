message(STATUS "---------Beginning cmake build of ld-chroma-encoder---------")
project(ld-chroma-encoder)

#ld-chroma-encoder SOURCES
set(SOURCES
    main.cpp
    encoder.cpp
    ntscencoder.cpp
    palencoder.cpp
    ../../library/tbc/dropouts.cpp
    ../../library/tbc/jsonio.cpp
    ../../library/tbc/lddecodemetadata.cpp
    ../../library/tbc/logging.cpp
    ../../library/tbc/vbidecoder.cpp
)

#ld-chroma-encoder HEADERS
set(HEADERS
    encoder.h
    ntscencoder.h
    palencoder.h
    ../../library/filter/firfilter.h
    ../../library/tbc/dropouts.h
    ../../library/tbc/jsonio.h
    ../../library/tbc/lddecodemetadata.h
    ../../library/tbc/logging.h
    ../../library/tbc/vbidecoder.h
)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

# ld-chroma-encoder executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

install(TARGETS ${PROJECT_NAME} DESTINATION "")
