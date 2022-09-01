message(STATUS "---------Beginning cmake build of ld-lds-converter ---------")
project(ld-lds-converter)

#ld-lds-converter SOURCES
set(SOURCES
    dataconverter.cpp
    main.cpp
)

# ld-lds-converter executable

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

# Link them to the project

install(TARGETS ${PROJECT_NAME})
