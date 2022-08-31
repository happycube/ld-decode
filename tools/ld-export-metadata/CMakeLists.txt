message(STATUS "---------Beginning cmake build of ld-export-metadata ---------")
project(ld-export-metadata)

#ld-export-metadata SOURCES
set(SOURCES
    closedcaptions.cpp
    csv.cpp
    ffmetadata.cpp
    main.cpp
)

#ld-export-metadata HEADERS
set(HEADERS
    closedcaptions.h
    csv.h
    ffmetadata.h
)

# ld-export-metadata executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")
