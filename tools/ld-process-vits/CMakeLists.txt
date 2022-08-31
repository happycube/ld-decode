message(STATUS "---------Beginning cmake build of ld-process-vits ---------")
project(ld-process-vits)

#ld-process-vits SOURCES
set(SOURCES
    main.cpp
    processingpool.cpp
    vitsanalyser.cpp
)

#ld-process-vits HEADERS
set(HEADERS
    processingpool.h
    vitsanalyser.h
)

# ld-process-vits executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
