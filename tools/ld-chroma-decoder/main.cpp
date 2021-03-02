/************************************************************************

    main.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2020 Simon Inns
    Copyright (C) 2019-2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>
#include <QScopedPointer>
#include <QThread>
#include <fstream>

#include "decoderpool.h"
#include "lddecodemetadata.h"
#include "logging.h"

#include "comb.h"
#include "monodecoder.h"
#include "ntscdecoder.h"
#include "palcolour.h"
#include "paldecoder.h"
#include "transformpal.h"

// Load the thresholds file for the Transform decoders, if specified. We must
// do this after PalColour has been configured, so we know how many values to
// expect.
//
// Return true on success; on failure, print a message and return false.
static bool loadTransformThresholds(QCommandLineParser &parser, QCommandLineOption &transformThresholdsOption, PalColour::Configuration &palConfig)
{
    if (!parser.isSet(transformThresholdsOption)) {
        // Nothing to load
        return true;
    }

    // Open the file
    QString filename = parser.value(transformThresholdsOption);
    std::ifstream thresholdsFile(filename.toStdString());
    if (thresholdsFile.fail()) {
        qCritical() << "Transform thresholds file could not be opened:" << filename;
        return false;
    }

    // Read threshold values from the file
    palConfig.transformThresholds.clear();
    while (true) {
        double value;
        thresholdsFile >> value;
        if (thresholdsFile.eof()) {
            break;
        }
        if (value < 0.0 || value > 1.0) {
            qCritical() << "Values in Transform thresholds file must be between 0 and 1:" << filename;
            return false;
        }
        if (thresholdsFile.fail()) {
            qCritical() << "Couldn't parse Transform thresholds file:" << filename;
            return false;
        }
        palConfig.transformThresholds.push_back(value);
    }

    // Check we've read the right number
    if (palConfig.transformThresholds.size() != palConfig.getThresholdsSize()) {
        qCritical() << "Transform thresholds file contained" << palConfig.transformThresholds.size()
                    << "values, expecting" << palConfig.getThresholdsSize() << "values:" << filename;
        return false;
    }

    thresholdsFile.close();
    return true;
}

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    setDebug(true);
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-chroma-decoder");
    QCoreApplication::setApplicationVersion(QString("Branch: %1 / Commit: %2").arg(APP_BRANCH, APP_COMMIT));
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-chroma-decoder - Colourisation filter for ld-decode\n"
                "\n"
                "(c)2018-2020 Simon Inns\n"
                "(c)2019-2020 Adam Sampson\n"
                "Contains PALcolour: Copyright (c)2018 William Andrew Steer\n"
                "Contains Transform PAL: Copyright (c)2014 Jim Easterbrook\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // -- General options --

    // Add the standard debug options --debug and --quiet
    addStandardDebugOptions(parser);

    // Option to specify a different JSON input file
    QCommandLineOption inputJsonOption(QStringList() << "input-json",
                                       QCoreApplication::translate("main", "Specify the input JSON file (default input.json)"),
                                       QCoreApplication::translate("main", "filename"));
    parser.addOption(inputJsonOption);

    // Option to select start frame (sequential) (-s)
    QCommandLineOption startFrameOption(QStringList() << "s" << "start",
                                        QCoreApplication::translate("main", "Specify the start frame number"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(startFrameOption);

    // Option to select length (-l)
    QCommandLineOption lengthOption(QStringList() << "l" << "length",
                                        QCoreApplication::translate("main", "Specify the length (number of frames to process)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(lengthOption);

    // Option to reverse the field order (-r)
    QCommandLineOption setReverseOption(QStringList() << "r" << "reverse",
                                       QCoreApplication::translate("main", "Reverse the field order to second/first (default first/second)"));
    parser.addOption(setReverseOption);

    // Option to specify chroma gain
    QCommandLineOption chromaGainOption(QStringList() << "chroma-gain",
                                        QCoreApplication::translate("main", "Gain factor applied to chroma components (default 1.0 NTSC, 0.5 PAL)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(chromaGainOption);

    // Option to select the output format (-p)
    QCommandLineOption outputFormatOption(QStringList() << "p" << "output-format",
                                       QCoreApplication::translate("main", "Output format (rgb, yuv, y4m; default rgb); RGB48, YUV444P16, GRAY16 pixel formats are supported"),
                                       QCoreApplication::translate("main", "output-format"));
    parser.addOption(outputFormatOption);

    // Option to set the black and white output flag (causes output to be black and white) (-b)
    QCommandLineOption setBwModeOption(QStringList() << "b" << "blackandwhite",
                                       QCoreApplication::translate("main", "Output in black and white"));
    parser.addOption(setBwModeOption);

    // Option to select which decoder to use (-f)
    QCommandLineOption decoderOption(QStringList() << "f" << "decoder",
                                     QCoreApplication::translate("main", "Decoder to use (pal2d, transform2d, transform3d, ntsc1d, ntsc2d, ntsc3d, ntsc3dnoadapt, mono; default automatic)"),
                                     QCoreApplication::translate("main", "decoder"));
    parser.addOption(decoderOption);

    // Option to select the number of threads (-t)
    QCommandLineOption threadsOption(QStringList() << "t" << "threads",
                                        QCoreApplication::translate("main", "Specify the number of concurrent threads (default number of logical CPUs)"),
                                        QCoreApplication::translate("main", "number"));
    parser.addOption(threadsOption);

    // -- NTSC decoder options --

    // Option to overlay the adaptive filter map
    QCommandLineOption showMapOption(QStringList() << "o" << "oftest",
                                     QCoreApplication::translate("main", "NTSC: Overlay the adaptive filter map (only used for testing)"));
    parser.addOption(showMapOption);

    // Option to set the white point to 75% (rather than 100%)
    QCommandLineOption whitePointOption(QStringList() << "w" << "white",
                                        QCoreApplication::translate("main", "NTSC: Use 75% white-point (default 100%)"));
    parser.addOption(whitePointOption);

    // Option to set the chroma noise reduction level
    QCommandLineOption chromaNROption(QStringList() << "chroma-nr",
                                      QCoreApplication::translate("main", "NTSC: Chroma noise reduction level in dB (default 0.0)"),
                                      QCoreApplication::translate("main", "number"));
    parser.addOption(chromaNROption);

    // Option to set the luma noise reduction level
    QCommandLineOption lumaNROption(QStringList() << "luma-nr",
                                    QCoreApplication::translate("main", "Luma noise reduction level in dB (default 1.0)"),
                                    QCoreApplication::translate("main", "number"));
    parser.addOption(lumaNROption);

    // -- PAL decoder options --

    // Option to use Simple PAL UV filter
    QCommandLineOption simplePALOption(QStringList() << "simple-pal",
                                           QCoreApplication::translate("main", "Transform: Use 1D UV filter (default 2D)"));
    parser.addOption(simplePALOption);

    // Option to select the Transform PAL filter mode
    QCommandLineOption transformModeOption(QStringList() << "transform-mode",
                                           QCoreApplication::translate("main", "Transform: Filter mode to use (level, threshold; default threshold)"),
                                           QCoreApplication::translate("main", "mode"));
    parser.addOption(transformModeOption);

    // Option to select the Transform PAL threshold
    QCommandLineOption transformThresholdOption(QStringList() << "transform-threshold",
                                                QCoreApplication::translate("main", "Transform: Uniform similarity threshold in 'threshold' mode (default 0.4)"),
                                                QCoreApplication::translate("main", "number"));
    parser.addOption(transformThresholdOption);

    // Option to select the Transform PAL thresholds file
    QCommandLineOption transformThresholdsOption(QStringList() << "transform-thresholds",
                                                 QCoreApplication::translate("main", "Transform: File containing per-bin similarity thresholds in 'threshold' mode"),
                                                 QCoreApplication::translate("main", "file"));
    parser.addOption(transformThresholdsOption);

    // Option to overlay the FFTs
    QCommandLineOption showFFTsOption(QStringList() << "show-ffts",
                                      QCoreApplication::translate("main", "Transform: Overlay the input and output FFTs"));
    parser.addOption(showFFTsOption);

    // -- Positional arguments --

    // Positional argument to specify input video file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input TBC file (- for piped input)"));

    // Positional argument to specify output video file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output file (omit or - for piped output)"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Standard logging options
    processStandardDebugOptions(parser);

    // Get the arguments from the parser
    QString inputFileName;
    QString outputFileName = "-";
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFileName = positionalArguments.at(0);
        outputFileName = positionalArguments.at(1);
    } else if (positionalArguments.count() == 1) {
        inputFileName = positionalArguments.at(0);
    } else {
        // Quit with error
        qCritical("You must specify the input TBC and output files");
        return -1;
    }

    // Check filename arguments are reasonable
    if (inputFileName == "-" && !parser.isSet(inputJsonOption)) {
        // Quit with error
        qCritical("With piped input, you must also specify the input JSON file");
        return -1;
    }
    if (inputFileName == outputFileName && outputFileName != "-") {
        // Quit with error
        qCritical("Input and output files cannot be the same");
        return -1;
    }

    qint32 startFrame = -1;
    qint32 length = -1;
    qint32 maxThreads = QThread::idealThreadCount();
    PalColour::Configuration palConfig;
    Comb::Configuration combConfig;
    MonoDecoder::Configuration monoConfig;

    if (parser.isSet(startFrameOption)) {
        startFrame = parser.value(startFrameOption).toInt();

        if (startFrame < 1) {
            // Quit with error
            qCritical("Specified startFrame must be at least 1");
            return -1;
        }
    }

    if (parser.isSet(lengthOption)) {
        length = parser.value(lengthOption).toInt();

        if (length < 1) {
            // Quit with error
            qCritical("Specified length must be greater than zero frames");
            return -1;
        }
    }

    if (parser.isSet(threadsOption)) {
        maxThreads = parser.value(threadsOption).toInt();

        if (maxThreads < 1) {
            // Quit with error
            qCritical("Specified number of threads must be greater than zero");
            return -1;
        }
    }

    if (parser.isSet(chromaGainOption)) {
        const double value = parser.value(chromaGainOption).toDouble();
        palConfig.chromaGain = value;
        combConfig.chromaGain = value;

        if (value < 0.0) {
            // Quit with error
            qCritical("Chroma gain must not be less than 0");
            return -1;
        }
    }

    if (parser.isSet(setBwModeOption)) {
        palConfig.chromaGain = 0.0;
        combConfig.chromaGain = 0.0;
    }

    // Determine the output format
    QString outputFormatName;
    if (parser.isSet(outputFormatOption)) {
        outputFormatName = parser.value(outputFormatOption);
    } else {
        outputFormatName = "rgb";
    }
    if (outputFormatName == "yuv" || outputFormatName == "y4m") {
        if (outputFormatName == "y4m") {
            palConfig.outputY4m = true;
            combConfig.outputY4m = true;
            monoConfig.outputY4m = true;
        }
        palConfig.outputYCbCr = true;
        palConfig.pixelFormat = palConfig.chromaGain > 0 ? Decoder::PixelFormat::YUV444P16 :
                                                           Decoder::PixelFormat::GRAY16;
        combConfig.outputYCbCr = true;
        combConfig.pixelFormat = combConfig.chromaGain > 0 ? Decoder::PixelFormat::YUV444P16 :
                                                             Decoder::PixelFormat::GRAY16;
        monoConfig.outputYCbCr = true;
        monoConfig.pixelFormat = Decoder::PixelFormat::GRAY16;
    } else if (outputFormatName != "rgb") {
        qCritical() << "Unknown output format " << outputFormatName;
        return -1;
    }

    if (parser.isSet(whitePointOption)) {
        combConfig.whitePoint75 = true;
    }

    if (parser.isSet(showMapOption)) {
        combConfig.showMap = true;
    }

    if (parser.isSet(chromaNROption)) {
        combConfig.cNRLevel = parser.value(chromaNROption).toDouble();

        if (combConfig.cNRLevel < 0.0) {
            // Quit with error
            qCritical("Chroma noise reduction cannot be negative");
            return -1;
        }
    }

    if (parser.isSet(lumaNROption)) {
        combConfig.yNRLevel = parser.value(lumaNROption).toDouble();
        palConfig.yNRLevel = parser.value(lumaNROption).toDouble();

        if (combConfig.yNRLevel < 0.0) {
            // Quit with error
            qCritical("Luma noise reduction cannot be negative");
            return -1;
        }
    }

    if (parser.isSet(transformModeOption)) {
        const QString name = parser.value(transformModeOption);

        if (name == "level") {
            palConfig.transformMode = TransformPal::levelMode;
        } else if (name == "threshold") {
            palConfig.transformMode = TransformPal::thresholdMode;
        } else {
            // Quit with error
            qCritical() << "Unknown Transform mode " << name;
            return -1;
        }
    }

    if (parser.isSet(simplePALOption)) {
        palConfig.simplePAL = true;
    }

    if (parser.isSet(transformThresholdOption)) {
        palConfig.transformThreshold = parser.value(transformThresholdOption).toDouble();

        if (palConfig.transformThreshold < 0.0 || palConfig.transformThreshold > 1.0) {
            // Quit with error
            qCritical("Transform threshold must be between 0 and 1");
            return -1;
        }
    }

    if (parser.isSet(showFFTsOption)) {
        palConfig.showFFTs = true;
        if (palConfig.outputY4m) {
            // Quit with error
            qCritical("Y4M output not available when showFFT is enabled");
            return -1;
        } else if (palConfig.outputYCbCr) {
            // Quit with error
            qCritical("YUV output not available when showFFT is enabled");
            return -1;
        }
    }

    // Work out the metadata filename
    QString inputJsonFileName = inputFileName + ".json";
    if (parser.isSet(inputJsonOption)) {
        inputJsonFileName = parser.value(inputJsonOption);
    }

    // Load the source video metadata
    LdDecodeMetaData metaData;
    if (!metaData.read(inputJsonFileName)) {
        qInfo() << "Unable to open ld-decode metadata file";
        return -1;
    }

    // Reverse field order if required
    if (parser.isSet(setReverseOption)) {
        qInfo() << "Expected field order is reversed to second field/first field";
        metaData.setIsFirstFieldFirst(false);
    }

    // Work out which decoder to use
    QString decoderName;
    if (parser.isSet(decoderOption)) {
        decoderName = parser.value(decoderOption);
    } else if (metaData.getVideoParameters().isSourcePal) {
        decoderName = "pal2d";
    } else {
        decoderName = "ntsc2d";
    }

    // Require ntsc3d if the map overlay is selected
    if (combConfig.showMap && decoderName != "ntsc3d") {
        qCritical() << "Can only show adaptive filter map with the ntsc3d decoder";
        return -1;
    }

    // Require transform2d/3d if the FFT overlay is selected
    if (palConfig.showFFTs && decoderName != "transform2d" && decoderName != "transform3d") {
        qCritical() << "Can only show FFTs with the transform2d/transform3d decoders";
        return -1;
    }

    // Select the decoder
    QScopedPointer<Decoder> decoder;
    if (decoderName == "pal2d") {
        decoder.reset(new PalDecoder(palConfig));
    } else if (decoderName == "transform2d") {
        palConfig.chromaFilter = PalColour::transform2DFilter;
        if (!loadTransformThresholds(parser, transformThresholdsOption, palConfig)) {
            return -1;
        }
        decoder.reset(new PalDecoder(palConfig));
    } else if (decoderName == "transform3d") {
        palConfig.chromaFilter = PalColour::transform3DFilter;
        if (!loadTransformThresholds(parser, transformThresholdsOption, palConfig)) {
            return -1;
        }
        decoder.reset(new PalDecoder(palConfig));
    } else if (decoderName == "ntsc1d") {
        combConfig.dimensions = 1;
        decoder.reset(new NtscDecoder(combConfig));
    } else if (decoderName == "ntsc2d") {
        combConfig.dimensions = 2;
        decoder.reset(new NtscDecoder(combConfig));
    } else if (decoderName == "ntsc3d") {
        combConfig.dimensions = 3;
        decoder.reset(new NtscDecoder(combConfig));
    } else if (decoderName == "ntsc3dnoadapt") {
        combConfig.dimensions = 3;
        combConfig.adaptive = false;
        decoder.reset(new NtscDecoder(combConfig));
    } else if (decoderName == "mono") {
        decoder.reset(new MonoDecoder(monoConfig));
    } else {
        qCritical() << "Unknown decoder " << decoderName;
        return -1;
    }

    // Perform the processing
    DecoderPool decoderPool(*decoder, inputFileName, metaData, outputFileName, startFrame, length, maxThreads);
    if (!decoderPool.process()) {
        return -1;
    }

    // Quit with success
    return 0;
}
