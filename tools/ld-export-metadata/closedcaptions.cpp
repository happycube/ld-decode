/************************************************************************

    closedcaptions.cpp

    ld-export-metadata - Export JSON metadata into other formats
    Copyright (C) 2019-2020 Adam Sampson
    Copyright (C) 2021 Simon Inns

    This file is part of ld-decode-tools.

    ld-export-metadata is free software: you can redistribute it and/or
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

#include "closedcaptions.h"

#include "vbidecoder.h"

#include <QtGlobal>
#include <QFile>
#include <QTextStream>
#include <set>
#include <vector>

using std::set;
using std::vector;

// The closed caption protocol is a stream of both text and control
// commands that instruct the player how to present the text including
// rolling it up, moving the cursor around, etc.
//
// This cannot be represented as a text file so, instead, spaces and
// new lines are used in the output to attempt to create as readable
// text in the output as possible.
//
// This function decodes the CC command and outputs a space, new-line
// or nothing.
QString processCCCommand(qint32 data0, qint32 data1)
{
    QString outputText;

    // Verify display control code
    if (data1 >= 0x20 && data1 <= 0x7F) {

        // Check for miscellaneous control codes (indicated by data0 & 01110110 == 00010100)
        if ((data0 & 0x76) == 0x14) {
            // Miscellaneous
            qint32 commandGroup = (data0 & 0x02) >> 1; // 0b00000010 >> 1
            qint32 commandType = (data1 & 0x0F); // 0b00001111

            if (commandGroup == 0) {
                // Normal command
                switch (commandType) {
                case 0:
                    qDebug() << "processCCCommand(): Miscellaneous command - Resume caption loading";
                    //outputText = "<C0>";
                    outputText = " ";
                    break;
                case 1:
                    qDebug() << "processCCCommand(): Miscellaneous command - Backspace";
                    //outputText = "<C1>";
                    break;
                case 2:
                    qDebug() << "processCCCommand(): Miscellaneous command - Reserved 1";
                    //outputText = "<C2>";
                    outputText = " ";
                    break;
                case 3:
                    qDebug() << "processCCCommand(): Miscellaneous command - Reserved 2";
                    //outputText = "<C3>";
                    break;
                case 4:
                    qDebug() << "processCCCommand(): Miscellaneous command - Delete to end of row";
                    //outputText = "<C4>";
                    outputText = " ";
                    break;
                case 5:
                    qDebug() << "processCCCommand(): Miscellaneous command - Roll-up captions, 2 rows";
                    //outputText = "<C5>";
                    break;
                case 6:
                    qDebug() << "processCCCommand(): Miscellaneous command - Roll-up captions, 3 rows";
                    //outputText = "<C6>";
                    break;
                case 7:
                    qDebug() << "processCCCommand(): Miscellaneous command - Roll-up captions, 4 rows";
                    //outputText = "<C7>";
                    break;
                case 8:
                    qDebug() << "processCCCommand(): Miscellaneous command - Flash on";
                    //outputText = "<C8>";
                    break;
                case 9:
                    qDebug() << "processCCCommand(): Miscellaneous command - Resume direct captioning";
                    //outputText = "<C9>";
                    break;
                case 10:
                    qDebug() << "processCCCommand(): Miscellaneous command - Text restart";
                    //outputText = "<C10>";
                    break;
                case 11:
                    qDebug() << "processCCCommand(): Miscellaneous command - Resume text display";
                    //outputText = "<C11>";
                    break;
                case 12:
                    qDebug() << "processCCCommand(): Miscellaneous command - Erase displayed memory";
                    //outputText = "<C12>";
                    break;
                case 13:
                    qDebug() << "processCCCommand(): Miscellaneous command - Carriage return";
                    //outputText = "<C13>";
                    break;
                case 14:
                    qDebug() << "processCCCommand(): Miscellaneous command - Erase non-displayed memory";
                    //outputText = "<C14>";
                    break;
                case 15:
                    qDebug() << "processCCCommand(): Miscellaneous command - End of caption (flip memories)";
                    //outputText = "<C15>";
                    outputText = "\n";
                    break;
                }
            } else {
                // Tab offset command
                switch (commandType) {
                case 1:
                    qDebug() << "processCCCommand(): Miscellaneous command - Tab offset (1 column)";
                    //outputText = "<T1>";
                    break;
                case 2:
                    qDebug() << "processCCCommand(): Miscellaneous command - Tab offset (2 columns)";
                    //outputText = "<T2>";
                    break;
                case 3:
                    qDebug() << "processCCCommand(): Miscellaneous command - Tab offset (3 columns)";
                    //outputText = "<T3>";
                    break;
                }
            }

            // Done
            return outputText;
        }

        // Check for midrow command code (indicated by data0 & 01110111 == 00010001)
        if ((data0 & 0x77) == 0x11) {
            qDebug() << "processCCCommand(): Midrow command";
            //outputText = "<MRC>";
        }
    } else {
        qDebug() << "processCCCommand(): Display control code invalid!" << data1;
    }

    return outputText;
}

// This function scans through the available metadata and extracts the CC
// data (present only on NTSC format discs) - the text is streamed out
// to a text file.
bool writeClosedCaptions(LdDecodeMetaData &metaData, const QString &fileName)
{
    const auto videoParameters = metaData.getVideoParameters();

    qint32 lastNonDisplayCommand = -1;
    qint32 lastDisplayCommand = -1;

    // Only NTSC discs can contain closed captions; so perform a basic sanity check
    if (videoParameters.isSourcePal) {
        qInfo() << "Video source is PAL which cannot contain closed captions";
        return false;
    }

    // Open the output file
    QFile file(fileName);
    if (!file.open(QFile::WriteOnly | QFile::Text)) {
        qDebug("writeClosedCaptions: Could not open file for output");
        return false;
    }
    QTextStream stream(&file);
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
    stream.setCodec("UTF-8");
#endif

    // Extract the closed captions data and stream to the text file
    for (qint32 fieldIndex = 1; fieldIndex <= videoParameters.numberOfSequentialFields; fieldIndex++) {
        QString decodedText;

        // Get the CC data from the metadata
        qint32 data0 = metaData.getFieldNtsc(fieldIndex).ccData0;
        qint32 data1 = metaData.getFieldNtsc(fieldIndex).ccData1;

        // Check incoming data is valid
        if (data0 != -1 && data1 != -1) {
            // Check for a non-display control code
            if (data0 >= 0x10 && data0 <= 0x1F) {
                if (data0 == lastNonDisplayCommand && data1 == lastDisplayCommand) {
                    // This is a command repeat; ignore
                } else {
                    // Non-display control code
                    qDebug() << "writeClosedCaptions(): Got non-display control code of" << data0 << "- ignoring";
                    decodedText = processCCCommand(data0, data1);
                    lastNonDisplayCommand = data0;
                    lastDisplayCommand = data1;
                }
            } else {
                // Normal text (2 characters)
                char string[3];
                string[0] = static_cast<char>(data0);
                string[1] = static_cast<char>(data1);
                string[2] = static_cast<char>(0);

                // Convert to QString and return
                decodedText = QString::fromLocal8Bit(string);
            }
        }

        // Send the text to the file
        stream << decodedText;
    }

    // Done!
    file.close();
    return true;
}
