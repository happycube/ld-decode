# For M_PI constant
add_compile_definitions(_USE_MATH_DEFINES)

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
    plotwidget.cpp
)

qt_add_resources(ld-analyse_SOURCES ld-analyse-resources.qrc)

if(WIN32)
set(APP_ICON_RESOURCE_WINDOWS "${CMAKE_CURRENT_SOURCE_DIR}/appicon.rc")

add_executable(ld-analyse MACOSX_BUNDLE
    ${ld-analyse_SOURCES}
	${APP_ICON_RESOURCE_WINDOWS})
elseif(UNIX)
	add_executable(ld-analyse MACOSX_BUNDLE
    ${ld-analyse_SOURCES})
endif()


target_include_directories(ld-analyse PRIVATE
    ${FFTW_INCLUDE_DIR}
)

target_link_libraries(ld-analyse PRIVATE
    Qt::Core Qt::Gui Qt::Widgets
    lddecode-library lddecode-chroma
)

if(WIN32)
    target_compile_definitions(ld-analyse PRIVATE
        NOMINMAX
        QUSB_LIBRARY
    )
    set_property(TARGET ld-analyse PROPERTY WIN32_EXECUTABLE true)
endif()

if(UNIX)
	install(TARGETS ld-analyse BUNDLE DESTINATION bin)
	
	# Install desktop integration files directly to XDG standard locations
	# This avoids hanging issues with xdg-* commands run via sudo
	
	# Install .tbc mime type definition
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/install/application-video-tbc.xml
		DESTINATION share/mime/packages)
	
	# Install application icons at various sizes
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/Graphics/16-analyse.png
		DESTINATION share/icons/hicolor/16x16/apps
		RENAME ld-analyse.png)
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/Graphics/32-analyse.png
		DESTINATION share/icons/hicolor/32x32/apps
		RENAME ld-analyse.png)
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/Graphics/64-analyse.png
		DESTINATION share/icons/hicolor/64x64/apps
		RENAME ld-analyse.png)
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/Graphics/128-analyse.png
		DESTINATION share/icons/hicolor/128x128/apps
		RENAME ld-analyse.png)
	
	# Install desktop menu entry
	install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/install/ld-analyse.desktop
		DESTINATION share/applications)
	
	# Post-install: update caches (only if update-* commands are available)
	# These are safe to fail and won't hang
	install(CODE "execute_process(COMMAND which update-mime-database OUTPUT_QUIET ERROR_QUIET RESULT_VARIABLE _have_update_mime)")
	install(CODE "if(NOT _have_update_mime)
		execute_process(COMMAND update-mime-database \${CMAKE_INSTALL_PREFIX}/share/mime OUTPUT_QUIET ERROR_QUIET)
	endif()")
	install(CODE "execute_process(COMMAND which update-desktop-database OUTPUT_QUIET ERROR_QUIET RESULT_VARIABLE _have_update_desktop)")
	install(CODE "if(NOT _have_update_desktop)
		execute_process(COMMAND update-desktop-database \${CMAKE_INSTALL_PREFIX}/share/applications OUTPUT_QUIET ERROR_QUIET)
	endif()")
	install(CODE "execute_process(COMMAND which gtk-update-icon-cache OUTPUT_QUIET ERROR_QUIET RESULT_VARIABLE _have_gtk_icon)")
	install(CODE "if(NOT _have_gtk_icon)
		execute_process(COMMAND gtk-update-icon-cache -f -t \${CMAKE_INSTALL_PREFIX}/share/icons/hicolor OUTPUT_QUIET ERROR_QUIET)
	endif()")
else()
	install(
			TARGETS ld-analyse
			BUNDLE DESTINATION bin
	)
endif()
