message(STATUS "---------Beginning cmake build of ld-process-vits ---------")
project(ld-process-vits)

#ld-process-vits SOURCES
set(SOURCES
    main.cpp
    processingpool.cpp
    vitsanalyser.cpp
)

# ld-process-vits executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
