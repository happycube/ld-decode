message(STATUS "---------Beginning cmake build of ld-discmap ---------")
project(ld-discmap)

#ld-discmap SOURCES
set(SOURCES
    discmap.cpp
    discmapper.cpp
    frame.cpp
    main.cpp
)

# ld-discmap executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
