message(STATUS "---------Beginning cmake build of ld-analyse---------")
project(ld-analyse)

# Name all the files
set(ld-analyse_SOURCES
    blacksnranalysisdialog.cpp blacksnranalysisdialog.ui
    busydialog.cpp busydialog.ui
    closedcaptionsdialog.cpp closedcaptionsdialog.ui
    main.cpp
    mainwindow.cpp mainwindow.ui
    oscilloscopedialog.cpp oscilloscopedialog.ui
    vectorscopedialog.cpp vectorscopedialog.ui
    aboutdialog.cpp aboutdialog.ui
    videoparametersdialog.cpp videoparametersdialog.ui
    chromadecoderconfigdialog.cpp chromadecoderconfigdialog.ui
    tbcsource.cpp
    vbidialog.cpp vbidialog.ui
    configuration.cpp
    dropoutanalysisdialog.cpp dropoutanalysisdialog.ui
    visibledropoutanalysisdialog.cpp visibledropoutanalysisdialog.ui
    whitesnranalysisdialog.cpp whitesnranalysisdialog.ui
)

qt_add_resources(ld-analyse_SOURCES ld-analyse-resources.qrc)

add_executable(ld-analyse MACOSX_BUNDLE
    ${ld-analyse_SOURCES})

target_link_libraries(ld-analyse PRIVATE
    Qt::Core Qt::Gui Qt::Widgets
    qwt::qwt
    fftw3
    ld-library ld-chroma-lib
)

if(WIN32)
    target_compile_definitions(ld-analyse PRIVATE
        NOMINMAX
        QUSB_LIBRARY
    )
endif()

install(TARGETS ld-analyse)
