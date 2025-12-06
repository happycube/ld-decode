cmake_minimum_required(VERSION 3.16)

project(ld-process-ac3)

if(MSVC)
    find_package(Getopt REQUIRED)
endif()

add_subdirectory(demodulate)
add_subdirectory(decode)
