message(STATUS "---------Beginning cmake build of ld-process-vbi ---------")
project(ld-process-vbi)

#ld-process-vbi SOURCES
set(SOURCES
    closedcaption.cpp
    decoderpool.cpp
    main.cpp
    fmcode.cpp
    vbilinedecoder.cpp
    whiteflag.cpp
)

# ld-process-vbi executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
