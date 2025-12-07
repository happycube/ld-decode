# Set the target name
set(TARGET_NAME efm)

# Source files
file(GLOB SOURCES "src/*.cpp")
# Drop legacy logging.cpp; use shared TBC logging instead
list(FILTER SOURCES EXCLUDE REGEX ".*/logging\\.cpp$")

# Create the static library
add_library(${TARGET_NAME} STATIC ${SOURCES})

# Add the include directories
target_include_directories(${TARGET_NAME} PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_include_directories(${TARGET_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/tools/library)

# Add the include directory for the ezpwd library
target_include_directories(${TARGET_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../libs/ezpwd/c++)

# Link Qt and shared lddecode-library (for TBC logging)
target_link_libraries(${TARGET_NAME} PUBLIC Qt::Core lddecode-library)

# Optionally, you can specify the output directory for the library
set_target_properties(${TARGET_NAME} PROPERTIES
    ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../efm/lib
)
