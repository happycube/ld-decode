message(STATUS "---------Beginning cmake build of ld-dropout-correct ---------")
project(ld-dropout-correct)

#ld-dropout-correct SOURCES
set(SOURCES
    correctorpool.cpp
    main.cpp
    dropoutcorrect.cpp
)

#ld-dropout-correct HEADERS
set(HEADERS
    correctorpool.h
    dropoutcorrect.h
)

# ld-dropout-correct executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
