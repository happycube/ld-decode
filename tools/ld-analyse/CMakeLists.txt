message(STATUS "---------Beginning cmake build of ld-analyse---------")
project(ld-analyse)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Name all the files
set(ld-analyse_SOURCES
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
    visibledropoutanalysisdialog.cpp visibledropoutanalysisdialog.h visibledropoutanalysisdialog.ui
    whitesnranalysisdialog.cpp whitesnranalysisdialog.h whitesnranalysisdialog.ui
)

qt_add_resources(ld-analyse_SOURCES ld-analyse-resources.qrc)

add_executable(ld-analyse MACOSX_BUNDLE
    ${ld-analyse_SOURCES})

find_path(QWT_INCLUDE_DIR
    NAMES qwt_plot.h
    HINTS ${QT_INCLUDE_DIR}
    PATH_SUFFIXES qwt qwt-qt5 qwt6
)

find_library(QWT_LIBRARY
    NAMES qwt qwt-qt5
    HINTS ${QT_LIBRARY_DIR}
)

target_link_libraries(ld-analyse PRIVATE
    Qt::Core
    Qt::Gui
    Qt::Widgets
    ${QWT_LIBRARY}
    fftw3
    ld-library
    ld-chroma-lib
)

message(STATUS "--------- QWT_LIBRARY = ${QWT_LIBRARY} ---------")
message(STATUS "--------- QWT_INCLUDE_DIR = ${QWT_INCLUDE_DIR} ---------")

target_include_directories(ld-analyse PUBLIC
    ${QWT_INCLUDE_DIR}
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

install(TARGETS ld-analyse
    BUNDLE DESTINATION .
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

#install(TARGETS ${PROJECT_NAME} DESTINATION "")
