# Adapted from GNURadio's version (GPL v3 or later):
# https://github.com/gnuradio/gnuradio/blob/main/cmake/Modules/FindQwt.cmake

# - try to find Qwt libraries and include files
# QWT_INCLUDE_DIR where to find qwt_global.h, etc.
# QWT_LIBRARIES libraries to link against
# QWT_FOUND If false, do not try to use Qwt
# qwt_global.h holds a string with the QWT version

pkg_check_modules(PC_QWT "Qt${QT_VERSION_MAJOR}Qwt6")
set(QWT_QT_VERSION qt${QT_VERSION_MAJOR})

find_path(
    QWT_INCLUDE_DIRS
    NAMES qwt_global.h
    HINTS ${PC_QWT_INCLUDEDIR} ${CMAKE_INSTALL_PREFIX}/include /include
    PATHS /usr/local/include /usr/include /opt/local/include /sw/include
          /usr/local/lib/qwt.framework/Headers
    PATH_SUFFIXES qwt-${QWT_QT_VERSION} qwt qwt6 qwt5 ${QWT_QT_VERSION}/qwt)

find_library(
    QWT_LIBRARIES
    NAMES ${PC_QWT_LIBRARIES} qwt6-${QWT_QT_VERSION} qwt-${QWT_QT_VERSION} qwt
    HINTS ${PC_QWT_LIBDIR} ${CMAKE_INSTALL_PREFIX}/lib ${CMAKE_INSTALL_PREFIX}/lib64 /lib
    PATHS /usr/local/lib /usr/lib /opt/local/lib /sw/lib /usr/local/lib/qwt.framework)

set(QWT_FOUND FALSE)
if(QWT_INCLUDE_DIRS)
    file(STRINGS "${QWT_INCLUDE_DIRS}/qwt_global.h" QWT_STRING_VERSION
         REGEX "QWT_VERSION_STR")
    set(QWT_WRONG_VERSION True)
    set(QWT_VERSION "No Version")
    string(REGEX MATCH "[0-9]+.[0-9]+.[0-9]+" QWT_VERSION ${QWT_STRING_VERSION})

    message(STATUS "Qwt Version: ${QWT_VERSION}")
    if(QWT_VERSION VERSION_LESS 6.0)
        message(FATAL_ERROR "Qwt must be at least version 6.0")
    endif()
    set(QWT_FOUND TRUE)
endif(QWT_INCLUDE_DIRS)

if(QWT_FOUND)
    # handle the QUIETLY and REQUIRED arguments and set QWT_FOUND to TRUE if
    # all listed variables are TRUE
    include(FindPackageHandleStandardArgs)
    find_package_handle_standard_args(Qwt DEFAULT_MSG QWT_LIBRARIES QWT_INCLUDE_DIRS)
    mark_as_advanced(QWT_LIBRARIES QWT_INCLUDE_DIRS)
    if(Qwt_FOUND AND NOT TARGET qwt::qwt)
        add_library(qwt::qwt INTERFACE IMPORTED)
        set_target_properties(
            qwt::qwt PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "${QWT_INCLUDE_DIRS}"
                                INTERFACE_LINK_LIBRARIES "${QWT_LIBRARIES}")
    endif()
else()
    if(Qwt_FIND_REQUIRED)
        message(FATAL_ERROR "Qwt is required but it was not found")
    endif()
endif(QWT_FOUND)
