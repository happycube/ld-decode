/************************************************************************

    main.cpp

    Time-Based Correction
    ld-decode - Software decode of Laserdiscs from raw RF
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode.

    ld-decode is free software: you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public License
    as published by the Free Software Foundation, either version 3 of
    the License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Email: simon.inns@gmail.com

************************************************************************/

#include <QCoreApplication>
#include <QDebug>
#include <QCommandLineParser>

// For the debug message handler
#include <QtGlobal>
#include <stdio.h>
#include <stdlib.h>

// Locals
#include "tbcpal.h"

// Global for debug output
bool showDebug = false;
bool showInfo = true;

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QByteArray localMsg = msg.toLocal8Bit();
    switch (type) {
    case QtDebugMsg:
        if (showDebug) {
            // If the code was compiled as 'release' the context.file will be NULL
            if (context.file != NULL) fprintf(stderr, "Debug: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Debug: %s\n", localMsg.constData());
        }
        break;
    case QtInfoMsg:
        if (showInfo) fprintf(stderr, "Info: %s\n", localMsg.constData());
        break;
    case QtWarningMsg:
        if (context.file != NULL) fprintf(stderr, "Warning: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Warning: %s\n", localMsg.constData());
        break;
    case QtCriticalMsg:
        if (context.file != NULL) fprintf(stderr, "Critical: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Critical: %s\n", localMsg.constData());
        break;
    case QtFatalMsg:
        if (context.file != NULL) fprintf(stderr, "Fatal: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Fatal: %s\n", localMsg.constData());
        abort();
    }
}

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    qInstallMessageHandler(debugOutputHandler);

    // Main core application
    QCoreApplication app(argc, argv);

    // General command line options parser set-up
    QCoreApplication::setApplicationName("Time-Based Correction");
    QCoreApplication::setApplicationVersion("2.0");

    QCommandLineParser parser;
    parser.setApplicationDescription(
                "PAL laserdisc time-based correction (TBC)\n"
                "Part of the Software Decode of Laserdiscs project\n"
                "(c)2018 Chad Page and Simon Inns\n"
                "LGPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Definition of boolean command line options:

    // Option to show debug (-d)
    QCommandLineOption showDebugOption("d",QCoreApplication::translate("main", "Show debug (generates lots of output!)"));
    parser.addOption(showDebugOption);

    // Option to select quiet mode (suppresses all debug and info message output) (-q)
    QCommandLineOption quietModeOption("q",QCoreApplication::translate("main", "Quiet mode (suppresses both debug and info messages - overrides -d)"));
    parser.addOption(quietModeOption);

    // Option to show difference between pixels (-p)
    QCommandLineOption showDifferenceBetweenPixelsOption("p",QCoreApplication::translate("main", "Show difference between pixels - untested"));
    parser.addOption(showDifferenceBetweenPixelsOption);

    // Option to select "magnetic video mode" - bottom-field first (-m)
    QCommandLineOption magneticVideoModeOption("m",QCoreApplication::translate("main", "Magnetic video mode (bottom-field first)"));
    parser.addOption(magneticVideoModeOption);

    // Option to flip fields (-F)
    QCommandLineOption flipFieldsOption("F",QCoreApplication::translate("main", "Flip fields"));
    parser.addOption(flipFieldsOption);

    // Option to output audio only (-A)
    QCommandLineOption audioOnlyOption("A",QCoreApplication::translate("main", "Output only audio - untested"));
    parser.addOption(audioOnlyOption);

    // Option to perform auto-set (-g)
    QCommandLineOption performAutoSetOption("g",QCoreApplication::translate("main", "Perform input video auto-ranging"));
    parser.addOption(performAutoSetOption);

    // Option to perform despackle (-n)
    QCommandLineOption performDespackleOption("n",QCoreApplication::translate("main", "Perform despackle - untested"));
    parser.addOption(performDespackleOption);

    // Option to perform freeze-frame (-f)
    QCommandLineOption performFreezeFrameOption("f",QCoreApplication::translate("main", "Perform freeze-frame - untested"));
    parser.addOption(performFreezeFrameOption);

    // Option to perform seven-five (-h)
    QCommandLineOption performSevenFiveOption("h",QCoreApplication::translate("main", "Perform seven-five - untested"));
    parser.addOption(performSevenFiveOption);

    // Option to perform high-burst (-H)
    QCommandLineOption performHighBurstOption("H",QCoreApplication::translate("main", "Perform high-burst - untested"));
    parser.addOption(performHighBurstOption);

    // Definition of command line options requiring text-based parameters:

    // Option to specify input video file (-i)
    QCommandLineOption sourceVideoFileOption(QStringList() << "i" << "source-video-file",
                QCoreApplication::translate("main", "Specify input video file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(sourceVideoFileOption);

    // Option to specify input audio file (-a)
    QCommandLineOption sourceAudioFileOption(QStringList() << "a" << "source-audio-file",
                QCoreApplication::translate("main", "Specify input audio file - untested"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(sourceAudioFileOption);

    // Option to specify output video file (-o)
    QCommandLineOption targetVideoFileOption(QStringList() << "o" << "target-video-file",
                QCoreApplication::translate("main", "Specify output video file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(targetVideoFileOption);

    // Option to specify output audio file (MISSING)
    //
    //

    // Definition of command line options requiring numerical parameters:

    // For tol and rot I have no idea what the correct range is for the parameters
    // so I've set it to 0.0-10.0 for the time-being

    // Option to set tol (-t)
    QCommandLineOption tolOption(QStringList() << "t" << "tol",
                QCoreApplication::translate("main", "Specify tol - untested"),
                QCoreApplication::translate("main", "0.0-10.0"));
    parser.addOption(tolOption);

    // Option to set rot detection level (-r)
    QCommandLineOption rotOption(QStringList() << "r" << "rot",
                QCoreApplication::translate("main", "Specify rot - untested"),
                QCoreApplication::translate("main", "0.0-10.0"));
    parser.addOption(rotOption);

    // Process the command line arguments given by the user
    parser.process(app);

    // Boolean options
    if (parser.isSet(showDebugOption)) {
        showDebug = true;
    }

    if (parser.isSet(quietModeOption)) {
        // Note: overrides -d
        showDebug = false;
        showInfo = false;
    }

    bool showDifferenceBetweenPixels = parser.isSet(showDifferenceBetweenPixelsOption);
    bool magneticVideoMode = parser.isSet(magneticVideoModeOption);
    bool flipFields = parser.isSet(flipFieldsOption);
    bool audioOnly = parser.isSet(audioOnlyOption);
    bool performAutoSet = parser.isSet(performAutoSetOption);
    bool performDespackle = parser.isSet(performDespackleOption);
    bool performFreezeFrame = parser.isSet(performFreezeFrameOption);
    bool performSevenFive = parser.isSet(performSevenFiveOption);
    bool performHighBurst = parser.isSet(performHighBurstOption);

    // Text-based parameter options
    QString sourceVideoFileParameter = parser.value(sourceVideoFileOption);
    QString sourceAudioFileParameter = parser.value(sourceAudioFileOption);
    QString targetVideoFileParameter = parser.value(targetVideoFileOption);

    // Numerical parameter options
    bool tol = parser.isSet(tolOption);
    bool rot = parser.isSet(rotOption);
    QString tolParameter = parser.value(tolOption);
    double_t tolParameterValue = 0;
    QString rotParameter = parser.value(rotOption);
    double_t rotParameterValue = 0;

    // Verify the command line arguments
    bool commandLineOptionsOk = true;

    // If the tol option is used verify the parameter
    if (tol) {
        // Verify the parameter is in range
        bool conversionOk;
        tolParameterValue = tolParameter.toDouble(&conversionOk);

        // Was the parameter a valid integer?
        if (conversionOk) {
            // Was the parameter in range?
            if (tolParameterValue > 10.0) {
                qCritical("The tol parameter specified with -t must be in the range of 0.0-10.0");
                commandLineOptionsOk = false;
            }
        }
    }

    // If the rot option is used verify the parameter
    if (rot) {
        // Verify the parameter is in range
        bool conversionOk;
        rotParameterValue = rotParameter.toDouble(&conversionOk);

        // Was the parameter a valid integer?
        if (conversionOk) {
            // Was the parameter in range?
            if (rotParameterValue > 10.0) {
                qCritical("The rot parameter specified with -r must be in the range of 0.0-10.0");
                commandLineOptionsOk = false;
            }
        }
    }

    // TO-DO:  You can only specifiy an audio file if a video file is also specified...
    // add in some code to check for this error condition and warn the user correctly.

    // If the command line options were ok then process, otherwise quit with error
    if (commandLineOptionsOk) {
        // Create a TBC PAL object
        // Passed parameter should be:
        // 10 for 10FSC
        // 32 for C32MHZ
        //  4 for 4FSC
        // Any other value causes FSC8 to be set

        // Note: Only tested with 32 set...
        TbcPal tbcPal(32);

        // Apply the optional command line parameter settings to the object
        if (parser.isSet(showDifferenceBetweenPixelsOption)) tbcPal.setShowDifferenceBetweenPixels(showDifferenceBetweenPixels);
        if (parser.isSet(magneticVideoModeOption)) tbcPal.setMagneticVideoMode(magneticVideoMode);
        if (parser.isSet(flipFieldsOption)) tbcPal.setFlipFields(flipFields);
        if (parser.isSet(audioOnlyOption)) tbcPal.setAudioOnly(audioOnly);
        if (parser.isSet(performAutoSetOption)) tbcPal.setPerformAutoSet(performAutoSet);
        if (parser.isSet(performDespackleOption)) tbcPal.setPerformDespackle(performDespackle);
        if (parser.isSet(performFreezeFrameOption)) tbcPal.setPerformFreezeFrame(performFreezeFrame);
        if (parser.isSet(performSevenFiveOption)) tbcPal.setPerformSevenFive(performSevenFive);
        if (parser.isSet(performHighBurstOption)) tbcPal.setPerformHighBurst(performHighBurst);
        if (parser.isSet(tolOption)) tbcPal.setTol(tolParameterValue);
        if (parser.isSet(rotOption)) tbcPal.setRot(rotParameterValue);

        // Apply the mandatory command line parameters to the object
        tbcPal.setSourceVideoFile(sourceVideoFileParameter);
        tbcPal.setSourceAudioFile(sourceAudioFileParameter);
        tbcPal.setTargetVideoFile(targetVideoFileParameter);

        // Execute PAL TBC
        tbcPal.execute();

    } else {
        // Command line options were not ok
        qDebug() << "main(): Exiting due to problems with the command line parameters";
        return -1;
    }

    // All done
    //return app.exec();
    return 0;
}
