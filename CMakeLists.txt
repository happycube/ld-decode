cmake_minimum_required(VERSION 3.16)
project(ld-decode)

# Enable testing
include(CTest)

# Find Python
find_package(Python3 3.6 REQUIRED COMPONENTS Interpreter)

# Include test definitions
include(cmake_modules/LdDecodeTests.cmake)
