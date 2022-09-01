message(STATUS "---------Beginning cmake build of ld-export-metadata ---------")
project(ld-export-metadata)

#ld-export-metadata SOURCES
set(SOURCES
    closedcaptions.cpp
    csv.cpp
    ffmetadata.cpp
    main.cpp
)

# ld-export-metadata executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
