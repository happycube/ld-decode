message(STATUS "---------Beginning cmake build of ld-disc-stacker ---------")
project(ld-disc-stacker)

#ld-disc-stacker SOURCES
set(SOURCES
    main.cpp
    stacker.cpp
    stackingpool.cpp
)

#ld-disc-stacker HEADERS
set(HEADERS
    stacker.h
    stackingpool.h
)

# ld-disc-stacker executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Widgets ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

target_link_libraries(${PROJECT_NAME} PRIVATE)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
