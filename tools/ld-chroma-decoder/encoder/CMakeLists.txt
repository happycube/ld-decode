message(STATUS "---------Beginning cmake build of ld-chroma-encoder---------")
project(ld-chroma-encoder)

#ld-chroma-encoder SOURCES
set(SOURCES
    main.cpp
    encoder.cpp
    ntscencoder.cpp
    palencoder.cpp
)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# ld-chroma-encoder executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

install(TARGETS ${PROJECT_NAME})
