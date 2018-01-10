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
#include "tbc.h"

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
                "Laserdisc time-based correction (TBC)\n"
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

    // Option to select PAL TBC mode (-p)
    QCommandLineOption palModeOption("p",QCoreApplication::translate("main", "PAL mode (default is NTSC)"));
    parser.addOption(palModeOption);

    // Option to select legacy PAL TBC (-l)
    QCommandLineOption palLegacyOption("l",QCoreApplication::translate("main", "Use legacy PAL TBC code - depreciated"));
    parser.addOption(palLegacyOption);

    // Option to select cxadc input sample format (-c)
    QCommandLineOption cxadcOption("c",QCoreApplication::translate("main", "cxadc 8-bit 28.8MSPS input format (default 16-bit 32MSPS)"));
    parser.addOption(cxadcOption);

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

    // Option to specify output audio file (-b)
    QCommandLineOption targetAudioFileOption(QStringList() << "b" << "target-audio-file",
                QCoreApplication::translate("main", "Specify output audio file"),
                QCoreApplication::translate("main", "file"));
    parser.addOption(targetAudioFileOption);

    // Option to select "magnetic video mode" - bottom-field first (-m)
    QCommandLineOption magneticVideoModeOption("m",QCoreApplication::translate("main", "Magnetic video mode (bottom-field first for VHS support)"));
    parser.addOption(magneticVideoModeOption);

    // Option to flip fields (-f)
    QCommandLineOption flipFieldsOption("f",QCoreApplication::translate("main", "Flip video fields"));
    parser.addOption(flipFieldsOption);

    // Option to output audio only (-s)
    QCommandLineOption audioOnlyOption("s",QCoreApplication::translate("main", "Output only audio"));
    parser.addOption(audioOnlyOption);

    // Option to perform freeze-frame (-z)
    QCommandLineOption performFreezeFrameOption("z",QCoreApplication::translate("main", "Perform freeze-frame"));
    parser.addOption(performFreezeFrameOption);

    // Option to set rot detection level (-r)
    QCommandLineOption rotOption(QStringList() << "r" << "rot",
                QCoreApplication::translate("main", "Specify rot - default 40.0"),
                QCoreApplication::translate("main", "0.0-1000.0"));
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

    bool palMode = parser.isSet(palModeOption);
    bool palLegacy = parser.isSet(palLegacyOption);
    bool cxadc = parser.isSet(cxadcOption);
    bool magneticVideoMode = parser.isSet(magneticVideoModeOption);
    bool flipFields = parser.isSet(flipFieldsOption);
    bool audioOnly = parser.isSet(audioOnlyOption);
    bool performFreezeFrame = parser.isSet(performFreezeFrameOption);

    // Text-based parameter options
    QString sourceVideoFileParameter = parser.value(sourceVideoFileOption);
    QString sourceAudioFileParameter = parser.value(sourceAudioFileOption);
    QString targetVideoFileParameter = parser.value(targetVideoFileOption);
    QString targetAudioFileParameter = parser.value(targetAudioFileOption);

    // Numerical parameter options
    bool rot = parser.isSet(rotOption);
    QString rotParameter = parser.value(rotOption);
    double_t rotParameterValue = 0;

    // Verify the command line arguments
    bool commandLineOptionsOk = true;

    // If the rot option is used verify the parameter
    if (rot) {
        // Verify the parameter is in range
        bool conversionOk;
        rotParameterValue = rotParameter.toDouble(&conversionOk);

        // Was the parameter a valid integer?
        if (conversionOk) {
            // Was the parameter in range?
            if (rotParameterValue > 1000.0) {
                qCritical("The rot parameter specified with -r must be in the range of 0.0-1000.0");
                commandLineOptionsOk = false;
            }
        }
    }

    // TO-DO:  You can only specifiy an audio file if a video file is also specified...
    // add in some code to check for this error condition and warn the user correctly.

    // If the command line options were ok then process, otherwise quit with error
    if (commandLineOptionsOk) {
        // Note: Only tested with 32 set...
        TbcPal tbcPal(32); // This will be removed soon

        Tbc tbcNtsc;

        // Use legacy PAL TBC or new universal TBC?
        if (palLegacy) {
            qWarning() << "Using legacy PAL mode - depreciated, use -p instead";
            // Apply the optional command line parameter settings to the PAL TBC object
            if (parser.isSet(magneticVideoModeOption)) tbcPal.setMagneticVideoMode(magneticVideoMode);
            if (parser.isSet(flipFieldsOption)) tbcPal.setFlipFields(flipFields);
            if (parser.isSet(audioOnlyOption)) tbcPal.setAudioOnly(audioOnly);
            if (parser.isSet(performFreezeFrameOption)) tbcPal.setPerformFreezeFrame(performFreezeFrame);
            if (parser.isSet(rotOption)) tbcPal.setRot(rotParameterValue);

            // Apply the mandatory command line parameters to the PAL TBC object
            tbcPal.setSourceVideoFile(sourceVideoFileParameter);
            tbcPal.setSourceAudioFile(sourceAudioFileParameter);
            tbcPal.setTargetVideoFile(targetVideoFileParameter);
            // Audio output not implemented yet!!!

            // Execute PAL TBC
            tbcPal.execute();
        } else {
            // Set the TBC mode
            if (cxadc && !palMode) tbcNtsc.setTbcMode(Tbc::ntsc_cxadc);
            if (cxadc && palMode) tbcNtsc.setTbcMode(Tbc::pal_cxadc);
            if (!cxadc && !palMode) tbcNtsc.setTbcMode(Tbc::ntsc_domdup);
            if (!cxadc && palMode) tbcNtsc.setTbcMode(Tbc::pal_domdup);

            // Apply the optional command line parameter settings to the NTSC TBC object
            if (parser.isSet(magneticVideoModeOption)) tbcNtsc.setMagneticVideoMode(magneticVideoMode);
            if (parser.isSet(flipFieldsOption)) tbcNtsc.setFlipFields(flipFields);
            if (parser.isSet(audioOnlyOption)) tbcNtsc.setAudioOutputOnly(audioOnly);
            if (parser.isSet(performFreezeFrameOption)) tbcNtsc.setPerformFreezeFrame(performFreezeFrame);
            if (parser.isSet(rotOption)) tbcNtsc.setRotDetectLevel(rotParameterValue);

            // Apply the mandatory command line parameters to the NTSC TBC object
            tbcNtsc.setSourceVideoFile(sourceVideoFileParameter);
            tbcNtsc.setSourceAudioFile(sourceAudioFileParameter);
            tbcNtsc.setTargetVideoFile(targetVideoFileParameter);
            tbcNtsc.setTargetAudioFile(targetAudioFileParameter);

            // Execute NTSC TBC
            tbcNtsc.execute();
        }

    } else {
        // Command line options were not ok
        qDebug() << "main(): Exiting due to problems with the command line parameters";
        return -1;
    }

    // All done
    //return app.exec();
    return 0;
}
