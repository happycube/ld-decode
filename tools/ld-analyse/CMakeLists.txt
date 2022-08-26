message( STATUS "---------Beginning cmake build of ld-analyse---------")

# Qt Widgets for Technical Applications
# available at http://www.http://qwt.sourceforge.net/
#
# The module defines the following variables:
#  Qwt_FOUND - the system has Qwt
#  QWT_INCLUDE_DIR - where to find qwt_plot.h
#  QWT_INCLUDE_DIRS - qwt includes
#  QWT_LIBRARY - where to find the Qwt library
#  QWT_LIBRARIES - aditional libraries
#  QWT_VERSION_STRING - version (ex. 5.2.1)
#
# It also defines this imported target:
#  Qwt::Qwt

#=============================================================================
# Copyright 2010-2013, Julien Schueller
# Copyright 2018-2020, Rolf Eike Beer
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met: 
# 
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer. 
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution. 
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNfind_library(QWT_LIBRARY_RELEASE NAMES qwt qwt-qt5 qt5-qwt PATH_SUFFIXES lib)ESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# The views and conclusions contained in the software and documentation are those
# of the authors and should not be interpreted as representing official policies, 
# either expressed or implied, of the FreeBSD Project.
#=============================================================================

if (Qt5Gui_FOUND)
  get_target_property(QT_INCLUDE_DIR Qt5::Gui INTERFACE_INCLUDE_DIRECTORIES)
endif ()

find_path ( QWT_INCLUDE_DIR
  NAMES qwt_plot.h
  HINTS ${QT_INCLUDE_DIR}
  PATH_SUFFIXES qwt qwt-qt5 qwt6
)

set ( QWT_INCLUDE_DIRS ${QWT_INCLUDE_DIR} )

# version
set ( _VERSION_FILE ${QWT_INCLUDE_DIR}/qwt_global.h )
if ( EXISTS ${_VERSION_FILE} )
  file ( STRINGS ${_VERSION_FILE} _VERSION_LINE REGEX "define[ ]+QWT_VERSION_STR" )
  if ( _VERSION_LINE )
    string ( REGEX REPLACE ".*define[ ]+QWT_VERSION_STR[ ]+\"([^\"]*)\".*" "\\1" QWT_VERSION_STRING "${_VERSION_LINE}" )
  endif ()
endif ()
unset ( _VERSION_FILE )

find_library ( QWT_LIBRARY
  NAMES qwt qwt-qt5
  HINTS ${QT_LIBRARY_DIR}
)

set ( QWT_LIBRARIES ${QWT_LIBRARY} )

include ( FindPackageHandleStandardArgs )
find_package_handle_standard_args( Qwt REQUIRED_VARS QWT_LIBRARY QWT_INCLUDE_DIR VERSION_VAR QWT_VERSION_STRING )

if (Qwt_FOUND AND NOT TARGET Qwt::Qwt)
  add_library(Qwt::Qwt UNKNOWN IMPORTED)
  set_target_properties(Qwt::Qwt PROPERTIES
                        INTERFACE_INCLUDE_DIRECTORIES "${QWT_INCLUDE_DIRS}"
                        IMPORTED_LOCATION "${QWT_LIBRARIES}")
endif ()

mark_as_advanced (
  QWT_LIBRARY
  QWT_INCLUDE_DIR
)

#
#
#
#
#
#
#
#
# Things above this line can go to an external file if possible
# Anything beneath stays here
#
#
#
#
#
#
#
#

cmake_minimum_required(VERSION 3.22)
project(ld-analyse VERSION 1.0 LANGUAGES CXX)

set(CMAKE_INCLUDE_CURRENT_DIR ON)
#list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake_modules")

# Set up AUTOMOC and some sensible defaults for runtime execution
# When using Qt 6.3, you can replace the code block below with
#qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
include(GNUInstallDirs)
set(CMAKE_AUTOUIC ON)

find_library(QWT_LIBRARY_RELEASE NAMES qwt qwt-qt5 qt5-qwt PATH_SUFFIXES lib)
find_package(QT NAMES Qt6 qwt-qt6 REQUIRED COMPONENTS Core HINTS Gui Widgets ${QT_LIBRARY_DIR})
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Gui Widgets)

# Name all the files
add_executable(ld-analyse MACOSX_BUNDLE
    blacksnranalysisdialog.cpp blacksnranalysisdialog.h blacksnranalysisdialog.ui
    busydialog.cpp busydialog.h busydialog.ui
    closedcaptionsdialog.cpp closedcaptionsdialog.h closedcaptionsdialog.ui
    main.cpp
    mainwindow.cpp mainwindow.h mainwindow.ui
    oscilloscopedialog.cpp oscilloscopedialog.h oscilloscopedialog.ui
    vectorscopedialog.cpp vectorscopedialog.h vectorscopedialog.ui
    aboutdialog.cpp aboutdialog.h aboutdialog.ui
    videoparametersdialog.cpp videoparametersdialog.h videoparametersdialog.ui
    chromadecoderconfigdialog.cpp chromadecoderconfigdialog.h chromadecoderconfigdialog.ui
    tbcsource.cpp tbcsource.h
    vbidialog.cpp vbidialog.h vbidialog.ui
    configuration.cpp configuration.h
    dropoutanalysisdialog.cpp dropoutanalysisdialog.h dropoutanalysisdialog.ui
    ../ld-chroma-decoder/palcolour.cpp ../ld-chroma-decoder/palcolour.h
    ../ld-chroma-decoder/comb.cpp ../ld-chroma-decoder/comb.h
    ../ld-chroma-decoder/componentframe.cpp ../ld-chroma-decoder/componentframe.h
    ../ld-chroma-decoder/outputwriter.cpp ../ld-chroma-decoder/outputwriter.h
    ../ld-chroma-decoder/transformpal.cpp ../ld-chroma-decoder/transformpal.h
    ../ld-chroma-decoder/transformpal2d.cpp ../ld-chroma-decoder/transformpal2d.h
    ../ld-chroma-decoder/transformpal3d.cpp ../ld-chroma-decoder/transformpal3d.h
    ../ld-chroma-decoder/framecanvas.cpp ../ld-chroma-decoder/framecanvas.h
    ../ld-chroma-decoder/sourcefield.cpp ../ld-chroma-decoder/sourcefield.h
    ../library/filter/firfilter.h
    ../library/tbc/dropouts.cpp ../library/tbc/dropouts.h
    ../library/tbc/filters.cpp ../library/tbc/filters.h
    ../library/tbc/jsonio.cpp ../library/tbc/jsonio.h
    ../library/tbc/lddecodemetadata.cpp ../library/tbc/lddecodemetadata.h
    ../library/tbc/linenumber.h
    ../library/tbc/logging.cpp ../library/tbc/logging.h
    ../library/tbc/sourcevideo.cpp ../library/tbc/sourcevideo.h
    ../library/tbc/vbidecoder.cpp ../library/tbc/vbidecoder.h
    visibledropoutanalysisdialog.cpp visibledropoutanalysisdialog.h visibledropoutanalysisdialog.ui
    whitesnranalysisdialog.cpp whitesnranalysisdialog.h whitesnranalysisdialog.ui
)

# Get the current working branch
execute_process(
	COMMAND git rev-parse --abbrev-ref HEAD
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_BRANCH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Get the latest abbreviated commit hash of the working branch
execute_process(
	COMMAND git log -1 --format=%h
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_COMMIT_HASH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Pass it on to the source code
add_definitions(-DAPP_BRANCH="\""+${GIT_BRANCH}+"\"" -DAPP_COMMIT="\""+${GIT_COMMIT_HASH}+"\"")

target_compile_definitions(ld-analyse PRIVATE
    QT_DEPRECATED_WARNINGS
)

target_include_directories(ld-analyse PUBLIC
    ${QWT_INCLUDE_DIRS}
)

target_link_libraries(ld-analyse PUBLIC Qt6::Core Qt6::Gui Qt6::Widgets fftw3 ld-tbc ld-filter ld-chroma-lib ${QWT_LIBRARY})

#message( STATUS "--------- Qwt_FOUND = ${Qwt_FOUND} ---------")
#message( STATUS "--------- QWT_LIBRARY = ${QWT_LIBRARY} ---------")
#message( STATUS "--------- QWT_LIBRARIES = ${QWT_LIBRARIES} ---------")
#message( STATUS "--------- QWT_INCLUDE_DIRS = ${QWT_INCLUDE_DIRS} ---------")
#message( STATUS "--------- QWT_INCLUDE_DIR = ${QWT_INCLUDE_DIR} ---------")
#message( STATUS "--------- QWT_VERSION_STRING = ${QWT_VERSION_STRING} ---------")

# Resources:
set(resources1_resource_files
    "Graphics/64-analyse.png"
    "Graphics/128-analyse.png"
    "Graphics/256-analyse.png"
    "Graphics/end-frame.svg"
    #"Graphics/ld-analyse logo.ai"
    #"Graphics/ld-analyse.icns"
    "Graphics/next-frame.svg" ${QWT_LIBRARY}
    "Graphics/oscilloscope-target.svg"
    "Graphics/prev-frame.svg"
    "Graphics/start-frame.svg"
    "Graphics/zoom-in.svg"
    "Graphics/zoom-original.svg"
    "Graphics/zoom-out.svg"
)

qt_add_resources(ld-analyse "resources1"
    PREFIX
        "/icons"
    FILES
        ${resources1_resource_files}
)

if(WIN32)
    target_compile_definitions(ld-analyse PRIVATE
        NOMINMAX
        QUSB_LIBRARY
    )

    target_link_libraries(ld-analyse PRIVATE
        # TODO: Does this depend on compiler?
        AdvAPI32
    )
endif()

#install(TARGETS ld-analyse
#    BUNDLE DESTINATION .
#    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
#)

install(TARGETS ${PROJECT_NAME} DESTINATION "")

# Consider using qt_generate_deploy_app_script() for app deployment if
# the project can use Qt 6.3. In that case rerun qmake2cmake with
# --min-qt-version=6.3.