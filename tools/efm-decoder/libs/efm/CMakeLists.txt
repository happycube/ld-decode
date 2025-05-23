# Set the target name
set(TARGET_NAME efm)

# Source files
file(GLOB SOURCES "src/*.cpp")

# Create the static library
add_library(${TARGET_NAME} STATIC ${SOURCES})

# Add the include directories
target_include_directories(${TARGET_NAME} PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Add the include directory for the ezpwd library
target_include_directories(${TARGET_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../libs/ezpwd/c++)
target_include_directories(${TARGET_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/tools/ld-process-efm/)

# Link Qt5 libraries
target_link_libraries(${TARGET_NAME} Qt::Core)

# Optionally, you can specify the output directory for the library
set_target_properties(${TARGET_NAME} PROPERTIES
    ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../efm/lib
)
