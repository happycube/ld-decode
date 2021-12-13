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

// Extract any available CC data and output it in Scenarist Closed Caption format (SCC) V1.0
// Protocol description:  http://www.theneitherworld.com/mcpoodle/SCC_TOOLS/DOCS/SCC_FORMAT.HTML
bool writeClosedCaptions(LdDecodeMetaData &metaData, const QString &fileName)
{
    const auto videoParameters = metaData.getVideoParameters();

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

    // Output the SCC V1.0 header
    stream << "Scenarist_SCC V1.0";

    // Set some constants for the timecode calculations
    double fieldsPerSecond = 29.97 * 2.0;
    double fieldsPerMinute = fieldsPerSecond * 60;
    double fieldsPerHour = fieldsPerMinute * 60;

    // Extract the closed captions data and stream to the text file
    bool captionInProgress = false;
    for (qint32 fieldIndex = 1; fieldIndex <= videoParameters.numberOfSequentialFields; fieldIndex++) {
        // Get the CC data bytes from the field
        qint32 data0 = metaData.getFieldNtsc(fieldIndex).ccData0;
        qint32 data1 = metaData.getFieldNtsc(fieldIndex).ccData1;

        // Check incoming data is valid
        if (data0 == -1 || data1 == -1) {
            // Invalid
        } else {
            // Valid
            if (data0 > 0 || data1 > 0) {
                // Caption data is present, do we need to output a timecode?
                if (captionInProgress == false) {
                    // Output a timecode followed by a tab character

                    // Since the subtitle is relative to the video we
                    // can simply calculate the timecode from the sequential
                    // field number (which should work even in the input
                    // is a snippet from a LaserDisc sample
                    //
                    // Note: There should probably be the option to choose if the
                    // subtitle timecodes are relative to the video or the VBI
                    // frame-number/CLV timecode; as both are useful depending on
                    // the use-case?
                    //
                    qint32 hh = static_cast<qint32>((fieldIndex / fieldsPerHour));
                    qint32 mm = static_cast<qint32>((fieldIndex / fieldsPerMinute)) % 60;
                    qint32 ss = (fieldIndex % static_cast<qint32>(fieldsPerMinute)) / fieldsPerSecond;
                    qint32 ff = fieldIndex % static_cast<qint32>(fieldsPerMinute) % static_cast<qint32>(fieldsPerSecond);

                    // Output is expecting fields, not frames, so approximate it
                    ff = ff / 2;

                    stream << "\n\n";
                    stream << QString("%1").arg(hh, 2, 10, QLatin1Char('0')) << ":" <<
                              QString("%1").arg(mm, 2, 10, QLatin1Char('0')) << ":" <<
                              QString("%1").arg(ss, 2, 10, QLatin1Char('0')) << ";" <<
                              QString("%1").arg(ff, 2, 10, QLatin1Char('0'));
                    stream << "\t";

                    // Set the caption in progress flag
                    captionInProgress = true;
                }

                // Output the 2 bytes of data as 2 hexadecimal values
                // i.e. 0x12 and 0x41 would be 1241 followed by a space
                // Hex output is padded with leading zeros
                stream << QString("%1").arg(data0, 2, 16, QLatin1Char('0'));
                stream << QString("%1").arg(data1, 2, 16, QLatin1Char('0'));
                stream << " ";
            } else {
                // No CC data for this frame
                captionInProgress = false;
            }
        }
    }

    // Add some trailing white space
    stream << "\n\n";

    // Done!
    file.close();
    return true;
}
