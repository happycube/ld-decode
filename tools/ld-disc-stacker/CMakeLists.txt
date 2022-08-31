message(STATUS "---------Beginning cmake build of ld-disc-stacker ---------")
project(ld-disc-stacker)

#ld-disc-stacker SOURCES
set(SOURCES
    main.cpp
    stacker.cpp
    stackingpool.cpp
    ../library/tbc/dropouts.cpp
    ../library/tbc/jsonio.cpp
    ../library/tbc/lddecodemetadata.cpp
    ../library/tbc/logging.cpp
    ../library/tbc/sourcevideo.cpp
    ../library/tbc/vbidecoder.cpp
)

#ld-disc-stacker HEADERS
set(HEADERS
    stacker.h
    stackingpool.h
    ../library/tbc/dropouts.h
    ../library/tbc/jsonio.h
    ../library/tbc/lddecodemetadata.h
    ../library/tbc/logging.h
    ../library/tbc/sourcevideo.h
    ../library/tbc/vbidecoder.h
)

find_package(Qt5 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

# ld-disc-stacker executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Widgets ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

target_link_libraries(${PROJECT_NAME} PRIVATE)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
