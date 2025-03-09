# Set the target name
set(TARGET_NAME vfs-verifier)

# Add all source files from main directory and subdirectories
file(GLOB_RECURSE SRC_FILES 
    ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/library/*.cpp
)

# Create the executable target first
add_executable(${TARGET_NAME} ${SRC_FILES})

# Then add include directories (including ezpwd)
target_include_directories(${TARGET_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../libs/efm/include
    ${Qt5Core_INCLUDE_DIRS}
    ${Qt5Widgets_INCLUDE_DIRS}
)

# Link the Qt libraries
target_link_libraries(${TARGET_NAME} PRIVATE Qt::Core)

# Link the efm library to your target
target_link_libraries(${TARGET_NAME} PRIVATE efm)

# Add the library directory for the EFM library
target_link_directories(${TARGET_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/../../libs/efm/lib)

install(TARGETS ${TARGET_NAME})