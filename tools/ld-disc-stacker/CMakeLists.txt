message(STATUS "---------Beginning cmake build of ld-disc-stacker ---------")
project(ld-disc-stacker)

#ld-disc-stacker SOURCES
set(SOURCES
    main.cpp
    stacker.cpp
    stackingpool.cpp
)

# ld-disc-stacker executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
