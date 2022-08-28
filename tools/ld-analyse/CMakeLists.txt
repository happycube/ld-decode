message( STATUS "---------Beginning cmake build of ld-analyse---------")
project(ld-analyse)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake_modules")
include_directories(Graphics)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

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

target_include_directories(ld-analyse PUBLIC
    ${QWT_INCLUDE_DIR}
)

target_link_libraries(ld-analyse PRIVATE Qt::Core Qt::Gui Qt::Widgets ${QWT_LIBRARY} fftw3 ld-library ld-chroma-lib)

#message( STATUS "--------- QT5_LIBRARY_DIR = ${QT5_LIBRARY_DIR} ---------")
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
        "/icons/Graphics"
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
