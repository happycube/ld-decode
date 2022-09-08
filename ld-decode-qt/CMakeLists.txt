cmake_minimum_required(VERSION 3.5)

project(ld-decode-qt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(ld-decode-qt main.cpp)

install(TARGETS ld-decode-qt
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
