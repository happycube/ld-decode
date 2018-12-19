/************************************************************************

    vbidecoder.cpp

    ld-process-vbi - VBI processor for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-vbi is free software: you can redistribute it and/or
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

#include "vbidecoder.h"

VbiDecoder::VbiDecoder(QObject *parent) : QObject(parent)
{

}

bool VbiDecoder::process(QString inputFileName)
{
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "VbiDecoder::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // Open the source video
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Process the VBI data for the fields
    for (qint32 fieldNumber = 1; fieldNumber <= sourceVideo.getNumberOfAvailableFields(); fieldNumber++) {
        SourceField *sourceField;
        VbiDecoder vbiDecoder;

        // Get the source field
        sourceField = sourceVideo.getVideoField(fieldNumber);

        // Get the existing field data from the metadata
        LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);
        if (field.isEven) qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(Even)";
        else  qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(Odd)";

        // Determine the 16-bit zero-crossing point
        qint32 zcPoint = videoParameters.white16bIre - videoParameters.black16bIre;

        // Get the VBI data from the field lines
        qDebug() << "VbiDecoder::process(): Getting field-lines for field" << fieldNumber;
        field.vbi.vbi16 = manchesterDecoder(getActiveVideoLine(sourceField, 16, videoParameters), zcPoint, videoParameters);
        field.vbi.vbi17 = manchesterDecoder(getActiveVideoLine(sourceField, 17, videoParameters), zcPoint, videoParameters);
        field.vbi.vbi18 = manchesterDecoder(getActiveVideoLine(sourceField, 18, videoParameters), zcPoint, videoParameters);

        // Show the VBI data as hexadecimal
        qInfo() << "Processing field" << fieldNumber <<
                    "16 =" << QString::number(field.vbi.vbi16, 16) <<
                    "17 =" << QString::number(field.vbi.vbi17, 16) <<
                    "18 =" << QString::number(field.vbi.vbi18, 16);

        // Translate the VBI data into a decoded VBI object
        field.vbi = translateVbi(field.vbi.vbi16, field.vbi.vbi17, field.vbi.vbi18);

        // Update the metadata for the field
        field.vbi.inUse = true;
        ldDecodeMetaData.updateField(field, fieldNumber);
        qDebug() << "VbiDecoder::process(): Updating metadata for field" << fieldNumber;
    }

    // Determine field order for the video based on the VBI
    bool determinationComplete = false;
    for (qint32 fieldNumber = 1; fieldNumber <= sourceVideo.getNumberOfAvailableFields(); fieldNumber++) {
        LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);

        if (field.vbi.type != LdDecodeMetaData::VbiDiscTypes::unknownDiscType) {
            // Is the disc CAV or CLV?
            if (field.vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) {
                // Does the field have a valid picture number?
                if (field.vbi.picNo != -1) {
                    qDebug() << "VbiDecoder::process(): Valid CAV picture number found in field" << fieldNumber;
                    // This is the first field in the frame
                    if (field.isEven) {
                        // This field is even, so field order is even/odd
                        videoParameters.isFieldOrderEvenOdd = true;
                        determinationComplete = true;
                    } else {
                        // This field is odd, so field order is odd/even
                        videoParameters.isFieldOrderEvenOdd = false;
                        determinationComplete = true;
                    }
                }
            } else {
                // Does the field have a valid CLV programme time code?
                if (field.vbi.timeCode.hr != -1) {
                    qDebug() << "VbiDecoder::process(): Valid CLV programme time code found in field" << fieldNumber;
                    // This is the first field in the frame
                    if (field.isEven) {
                        // This field is even, so field order is even/odd
                        videoParameters.isFieldOrderEvenOdd = true;
                        determinationComplete = true;
                    } else {
                        // This field is odd, so field order is odd/even
                        videoParameters.isFieldOrderEvenOdd = false;
                        determinationComplete = true;
                    }
                }
            }
        }

        // Done?
        if (determinationComplete) break;
    }

    if (determinationComplete) {
        if (videoParameters.isFieldOrderEvenOdd) qInfo() << "Field order is Even then Odd";
        else qInfo() << "Field order is Odd then Even";
        videoParameters.isFieldOrderValid = true;
        ldDecodeMetaData.setVideoParameters(videoParameters);
    } else qInfo() << "Field order could not be determined from the VBI data";

    // Write the metadata file
    QString outputFileName = inputFileName + ".json";
    ldDecodeMetaData.write(outputFileName);
    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    return true;
}

// Private method to translate the values of the VBI lines into VBI data
LdDecodeMetaData::Vbi VbiDecoder::translateVbi(qint32 vbi16, qint32 vbi17, qint32 vbi18)
{
    LdDecodeMetaData::Vbi vbi;

    // Set defaults
    vbi.vbi16 = vbi16;
    vbi.vbi17 = vbi17;
    vbi.vbi18 = vbi18;
    vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
    vbi.leadIn = false;
    vbi.leadOut = false;
    vbi.userCode = "";
    vbi.picNo = -1;
    vbi.picStop = false;
    vbi.chNo = -1;
    vbi.timeCode.hr = -1;
    vbi.timeCode.min = -1;

    vbi.statusCode.valid = false;
    vbi.statusCode.cx = false;
    vbi.statusCode.size = false;
    vbi.statusCode.side = false;
    vbi.statusCode.teletext = false;
    vbi.statusCode.dump = false;
    vbi.statusCode.fm = false;
    vbi.statusCode.digital = false;
    vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
    vbi.statusCode.parity = false;

    vbi.statusCodeAm2.valid = false;
    vbi.statusCodeAm2.cx = false;
    vbi.statusCodeAm2.size = false;
    vbi.statusCodeAm2.side = false;
    vbi.statusCodeAm2.teletext = false;
    vbi.statusCodeAm2.copy = false;
    vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;

    vbi.clvPicNo.sec = -1;
    vbi.clvPicNo.picNo = -1;

    // IEC 60857-1986 - 10.1.1 Lead-in --------------------------------------------------------------------------------

    // Check for lead-in on lines 17 and 18
    if ((vbi17 == 0x88FFFF) ||
            (vbi18 == 0x88FFFF)) {
        qDebug() << "VbiDecoder::translateVbi(): VBI Lead-in";
        vbi.leadIn = true;
    }

    // IEC 60857-1986 - 10.1.2 Lead-out -------------------------------------------------------------------------------

    // Check for lead-out on lines 17 and 18
    if ((vbi17 == 0x80EEEE) ||
            (vbi18 == 0x80EEEE)) {
        qDebug() << "VbiDecoder::translateVbi(): VBI Lead-out";
        vbi.leadOut = true;
    }

    // IEC 60857-1986 - 10.1.3 Picture numbers ------------------------------------------------------------------------

    // Check for picture number on lines 17 and 18
    quint32 bcdPictureNumber = 0;

    if ( (vbi17 & 0xF00000) == 0xF00000 ) {
        bcdPictureNumber = vbi17 & 0x07FFFF;
    } else if ( (vbi18 & 0xF00000) == 0xF00000 ) {
        bcdPictureNumber = vbi18 & 0x07FFFF;
    }

    if (bcdPictureNumber != 0) {
        // Peform BCD to integer conversion:
        vbi.picNo =
            (10000 * ((bcdPictureNumber & 0xF0000) / (16*16*16*16))) +
            ( 1000 * ((bcdPictureNumber & 0x0F000) / (16*16*16))) +
            (  100 * ((bcdPictureNumber & 0x00F00) / (16*16))) +
            (   10 * ((bcdPictureNumber & 0x000F0) / 16)) +
            (        ((bcdPictureNumber & 0x0000F)));

        // IEC 60856 amendment 2 states maximum picture number is 79,999
        if (vbi.picNo > 0 && vbi.picNo < 80000) {
            qDebug() << "VbiDecoder::translateVbi(): VBI picture number is" << vbi.picNo;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI picture number is" << vbi.picNo << "(out of range!)";
        }
    }

    // IEC 60857-1986 - 10.1.4 Picture stop code ----------------------------------------------------------------------

    // Check for picture stop code on lines 16 and 17
    if ((vbi16 == 0x82CFFF) ||
            (vbi17 == 0x82CFFF)) {
        vbi.picStop = true;
        qDebug() << "VbiDecoder::translateVbi(): VBI Picture stop code flagged";
    }

    // IEC 60857-1986 - 10.1.5 Chapter numbers ------------------------------------------------------------------------

    // Check for chapter number on lines 17 and 18
    quint32 bcdChapterNumber = 0;

    if ( (vbi17 & 0xF00FFF) == 0x800DDD ) {
        bcdChapterNumber = (vbi17 & 0x07F000) >> 12;
    } else if ( (vbi18 & 0xF00FFF) == 0x800DDD ) {
        bcdChapterNumber = (vbi18 & 0x07F000) >> 12;
    }

    if (bcdChapterNumber != 0) {
        // Peform BCD to integer conversion:
        vbi.chNo =
                (   10 * ((bcdChapterNumber & 0x000F0) / 16)) +
                (        ((bcdChapterNumber & 0x0000F)));

        qDebug() << "VbiDecoder::translateVbi(): VBI Chapter number is" << vbi.chNo;
    }

    // IEC 60857-1986 - 10.1.6 Programme time code --------------------------------------------------------------------

    bool clvProgrammeTimeCodeAvailable = false;
    // Check for programme time code on lines 17 and 18
    if ( (vbi17 & 0xF0FF00) == 0xF0DD00 ) {
        vbi.timeCode.hr = (vbi17 & 0x0F0000) >> 16;
        vbi.timeCode.min = (vbi17 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    } else if ( (vbi18 & 0xF0FF00) == 0xF0DD00 ) {
        vbi.timeCode.hr = (vbi18 & 0x0F0000) >> 16;
        vbi.timeCode.min = (vbi18 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    }

    if (clvProgrammeTimeCodeAvailable) {
        // Perform BCD conversion
        vbi.timeCode.hr =
                (   10 * ((vbi.timeCode.hr & 0x000F0) / 16)) +
                (        ((vbi.timeCode.hr & 0x0000F)));
        vbi.timeCode.min =
                (   10 * ((vbi.timeCode.min & 0x000F0) / 16)) +
                (        ((vbi.timeCode.min & 0x0000F)));

        qDebug() << "VbiDecoder::translateVbi(): VBI CLV programme time code is" <<
                    vbi.timeCode.hr << "hours," <<
                    vbi.timeCode.min << "minutes";
    }

    // IEC 60857-1986 - 10.1.7 Constant linear velocity code ----------------------------------------------------------

    // Check for CLV code on line 17
    vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;

    if ( vbi17 == 0x87FFFF ) {
        vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;
    } else vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;

    if (vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) qDebug() << "VbiDecoder::translateVbi(): VBI Disc type is CAV";
    else qDebug() << "VbiDecoder::translateVbi(): VBI Disc type is CLV";

    // IEC 60857-1986 - 10.1.8 Programme status code ------------------------------------------------------------------

    // Check for programme status code on line 16
    qint32 statusCode = 0;
    if (((vbi16 & 0xFFF000) == 0x8DC000) || ((vbi16 & 0xFFF000) == 0x8BA000)) {
        statusCode = vbi16;
    }

    if (statusCode != 0) {
        // Programme status code is available, decode it...
        vbi.statusCode.valid = true;

        // CX sound on or off?
        if ((statusCode & 0x0FF000) == 0x0DC000) {
            qDebug() << "VbiDecoder::translateVbi(): VBI CX sound is on";
            vbi.statusCode.cx = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI CX sound is off";
            vbi.statusCode.cx = false;
        }

        // Get the x3, x4 and x5 parameters
        quint32 x3 = (statusCode & 0x000F00) >> 8;
        quint32 x4 = (statusCode & 0x0000F0) >> 4;
        quint32 x5 = (statusCode & 0x00000F);

        quint32 x4Check = hammingCode(x4, x5);
        if (x4 == x4Check) {
            vbi.statusCode.parity = true;
            qDebug() << "VbiDecoder::translateVbi(): VBI Programme status parity check passed";
        } else {
            vbi.statusCode.parity = false;
            qDebug() << "VbiDecoder::translateVbi(): VBI Programme status parity check failed - x4 =" << x4 << "corrected to" << x4Check;
            x4 = x4Check; // Replace data with corrected version
        }

        // Get the disc size (12 inch or 8 inch) from x31
        if ((x3 & 0x08) == 0x08) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc is 8 inch";
            vbi.statusCode.size = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc is 12 inch";
            vbi.statusCode.size = true;
        }

        // Get the disc side (first or second) from x32
        if ((x3 & 0x04) == 0x04) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc side 2";
            vbi.statusCode.side = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc side 1";
            vbi.statusCode.side = true;
        }

        // Get the teletext presence (present or not present) from x33
        if ((x3 & 0x02) == 0x02) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Disc contains teletext";
            vbi.statusCode.teletext = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Disc does not contain teletext";
            vbi.statusCode.teletext = false;
        }

        // Get the analogue/digital video flag from x42
        if ((x4 & 0x04) == 0x04) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Video data is digital";
            vbi.statusCode.digital = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Video data is analogue";
            vbi.statusCode.digital = false;
        }

        // The audio channel status is given by x41, x34, x43 and x44 combined
        // (giving 16 possible audio status results)
        quint32 audioStatus = 0;
        if ((x4 & 0x08) == 0x08) audioStatus += 8; // X41 X34 X43 X44
        if ((x3 & 0x01) == 0x01) audioStatus += 4;
        if ((x4 & 0x02) == 0x02) audioStatus += 2;
        if ((x4 & 0x01) == 0x01) audioStatus += 1;
        qDebug() << "VbiDecoder::translateVbi(): VBI Programme status code - audio status is" << audioStatus;

        // Configure according to the audio status code
        switch(audioStatus) {
        case 0:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 0 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = stereo";
            break;
        case 1:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 1 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = mono";
            break;
        case 2:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 2 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = futureUse";
            break;
        case 3:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 3 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = bilingual";
            break;
        case 4:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 4 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = stereo_stereo";
            break;
        case 5:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 5 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = stereo_bilingual";
            break;
        case 6:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 6 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = crossChannelStereo";
            break;
        case 7:
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 7 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = bilingual_bilingual";
            break;
        case 8:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 8 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 9:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 9 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 10:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 10 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = futureUse";
            break;
        case 11:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 11 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 12:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 12 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = stereo_dump";
            break;
        case 13:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 13 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = stereo_dump";
            break;
        case 14:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 14 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = bilingual_dump";
            break;
        case 15:
            vbi.statusCode.dump = true;
            vbi.statusCode.fm = true;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 15 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = bilingual_dump";
            break;
        default:
            qDebug() << "VbiDecoder::translateVbi(): VBI - Invalid audio status code!";
            vbi.statusCode.dump = false;
            vbi.statusCode.fm = false;
            vbi.statusCode.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
        }
    } else {
        vbi.statusCode.valid = false;
    }

    // IEC 60857-1986 - 10.1.8 Programme status code (IEC Amendment 2) ------------------------------------------------

    // Check for programme status code on line 16
    qint32 statusCodeAm2 = 0;
    if (((vbi16 & 0xFFF000) == 0x8DC000) || ((vbi16 & 0xFFF000) == 0x8BA000)) {
        statusCodeAm2 = vbi16;
    }

    if (statusCodeAm2 != 0) {
        // Programme status code is available, decode it...
        vbi.statusCodeAm2.valid = true;

        // CX sound on or off?
        if ((statusCode & 0x0FF000) == 0x0DC000) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) CX sound is on";
            vbi.statusCodeAm2.cx = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) CX sound is off";
            vbi.statusCodeAm2.cx = false;
        }

        // Get the x3, x4 and x5 parameters
        quint32 x3 = (statusCode & 0x000F00) >> 8;
        quint32 x4 = (statusCode & 0x0000F0) >> 4;
        //quint32 x5 = (statusCode & 0x00000F);

        // Get the disc size (12 inch or 8 inch) from x31
        if ((x3 & 0x08) == 0x08) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Laserdisc is 8 inch";
            vbi.statusCodeAm2.size = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Laserdisc is 12 inch";
            vbi.statusCodeAm2.size = true;
        }

        // Get the disc side (first or second) from x32
        if ((x3 & 0x04) == 0x04) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Laserdisc side 2";
            vbi.statusCodeAm2.side = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Laserdisc side 1";
            vbi.statusCodeAm2.side = true;
        }

        // Get the teletext presence (present or not present) from x33
        if ((x3 & 0x02) == 0x02) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Disc contains teletext";
            vbi.statusCodeAm2.teletext = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Disc does not contain teletext";
            vbi.statusCodeAm2.teletext = false;
        }

        // Get the copy/no copy flag from x34
        if ((x3 & 0x01) == 0x01) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Copy permitted";
            vbi.statusCodeAm2.copy = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Copy prohibited";
            vbi.statusCodeAm2.copy = false;
        }

        // The audio channel status is given by x41, x42, x43 and x44 combined
        // (giving 16 possible audio status results)
        quint32 audioStatus = 0;
        if ((x4 & 0x08) == 0x08) audioStatus += 8; // X41 X42 X43 X44
        if ((x4 & 0x04) == 0x01) audioStatus += 4;
        if ((x4 & 0x02) == 0x02) audioStatus += 2;
        if ((x4 & 0x01) == 0x01) audioStatus += 1;
        qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Programme status code - audio status is" << audioStatus;

        // Configure according to the audio status code
        switch(audioStatus) {
        case 0:
            vbi.statusCodeAm2.standard = true;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 0 - isVideoSignalStandard = true - soundMode = stereo";
            break;
        case 1:
            vbi.statusCodeAm2.standard = true;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 1 - isVideoSignalStandard = true - soundMode = mono";
            break;
        case 2:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 2 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 3:
            vbi.statusCodeAm2.standard = true;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 3 - isVideoSignalStandard = true - soundMode = bilingual";
            break;
        case 4:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 4 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 5:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 5 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 6:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 6 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 7:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 7 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 8:
            vbi.statusCodeAm2.standard = true;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 8 - isVideoSignalStandard = true - soundMode = mono_dump";
            break;
        case 9:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 9 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 10:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 10 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 11:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 11 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 12:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 12 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 13:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 13 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 14:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 14 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 15:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 15 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        default:
            vbi.statusCodeAm2.standard = false;
            vbi.statusCodeAm2.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) - Invalid audio status code!";
        }
    } else {
        vbi.statusCodeAm2.valid = false;
    }

    // IEC 60857-1986 - 10.1.9 Users code -----------------------------------------------------------------------------

    // Check for users code on line 16
    qint32 usersCode = 0;

    if ((vbi16 & 0xF0F000) == 0x80D000) {
        usersCode = vbi16;
    }

    if (usersCode != 0) {
        // User code found
        quint32 x1 = (usersCode & 0x0F0000) >> 16;
        quint32 x3x4x5 = (usersCode & 0x000FFF);

        // x1 should be 0x00-0x07, x3-x5 are 0x00-0x0F
        if (x1 > 7) qDebug() << "VbiDecoder::translateVbi(): VBI invalid user code, X1 is > 7";

        // Add the two results together to get the user code
        vbi.userCode = QString::number(x1, 16).toUpper() + QString::number(x3x4x5, 16).toUpper();
        qDebug() << "VBI user code is" << vbi.userCode;
    }

    // IEC 60857-1986 - 10.1.10 CLV picture number --------------------------------------------------------------------

    // Check for CLV picture number on line 16
    qint32 clvPictureNumber = 0;

    if ((vbi16 & 0xF0F000) == 0x80E000) {
        clvPictureNumber = vbi16;
    }

    if (clvPictureNumber != 0) {
        // Get the x1, x3, x4 and x5 parameters
        qint32 x1   = (clvPictureNumber & 0x0F0000) >> 16;
        qint32 x3   = (clvPictureNumber & 0x000F00) >> 8;

        qint32 x4   = (clvPictureNumber & 0x0000F0) >> 4;
        qint32 x5   = (clvPictureNumber & 0x00000F);

        vbi.clvPicNo.sec = ((x1 - 10) * 10) + x3;
        vbi.clvPicNo.picNo = (x4  * 10) + x5;

        qDebug() << "VbiDecoder::translateVbi(): VBI CLV picture number is" <<
                    vbi.clvPicNo.sec << "seconds," <<
                    vbi.clvPicNo.picNo << "picture number";
    }

    return vbi;
}

// Private method to verifiy hamming code
quint32 VbiDecoder::hammingCode(quint32 x4, quint32 x5)
{
    // Hamming code parity check and correction

    // X4 is a1, a2, a3, a4
    // X5 is c1, c2, c3
    // U = a1, a2, a3, a4, c1, c2, c3
    quint32 u[7];

    if ((x4 & 0x8) == 0x8) u[6] = 1; else u[6] = 0;
    if ((x4 & 0x4) == 0x4) u[5] = 1; else u[5] = 0;
    if ((x4 & 0x2) == 0x2) u[4] = 1; else u[4] = 0;
    if ((x4 & 0x1) == 0x1) u[3] = 1; else u[3] = 0;
    if ((x5 & 0x8) == 0x8) u[2] = 1; else u[2] = 0;
    if ((x5 & 0x4) == 0x4) u[1] = 1; else u[1] = 0;
    if ((x5 & 0x2) == 0x2) u[0] = 1; else u[0] = 0;

    quint32 c, c1, c2, c3;
    c1 = u[6] ^ u[4] ^ u[2] ^ u[0];
    c2 = u[5] ^ u[4] ^ u[1] ^ u[0];
    c3 = u[3] ^ u[2] ^ u[1] ^ u[0];

    c = c3 * 4 + c2 * 2 + c1;

    if (c == 0) {
        // Check successful
        return x4;
    } else {
        // Check unsuccessful

        // Correct the bit
        if(u[7 - c] == 0) u[7 - c] = 1;
        else u[7 - c] = 0;

        quint32 x4Corrected = 0;
        if (u[6] == 1) x4Corrected += 8;
        if (u[5] == 1) x4Corrected += 4;
        if (u[4] == 1) x4Corrected += 2;
        if (u[3] == 1) x4Corrected += 1;

        qDebug() << "VbiDecoder::hammingCode():" << x4 << "corrected to" << x4Corrected << "due to error in bit" << c;
        return x4Corrected;
    }
}

// Private method to get a single scanline of greyscale data
QByteArray VbiDecoder::getActiveVideoLine(SourceField *sourceField, qint32 fieldLine,
                                        LdDecodeMetaData::VideoParameters videoParameters)
{
    // Range-check the scan line
    if (fieldLine > videoParameters.fieldHeight || fieldLine < 1) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return QByteArray();
    }

    qint32 startPointer = ((fieldLine - 1) * videoParameters.fieldWidth * 2) + (videoParameters.blackLevelEnd * 2);
    qint32 length = (videoParameters.activeVideoEnd - videoParameters.blackLevelEnd) * 2;

    return sourceField->getFieldData().mid(startPointer, length);
}

// Private method to read a 24-bit biphase coded signal (manchester code) from a field line
qint32 VbiDecoder::manchesterDecoder(QByteArray lineData, qint32 zcPoint,
                                     LdDecodeMetaData::VideoParameters videoParameters)
{
    qint32 result = 0;
    QVector<bool> manchesterData = getTransitionMap(lineData, zcPoint);

    // Get the number of samples for 1.5us
    qreal fJumpSamples = videoParameters.samplesPerUs * 1.5;
    qint32 jumpSamples = static_cast<qint32>(fJumpSamples);

    // Keep track of the number of bits decoded
    qint32 decodeCount = 0;

    // Find the first transition
    qint32 x = 0;
    while (x < manchesterData.size() && manchesterData[x] == false) {
        x++;
    }

    if (x < manchesterData.size()) {
        // Plot the first transition (which is always 01)
        result += 1;
        decodeCount++;

        // Find the rest of the transitions based on the expected clock rate of 2us per cell window
        while (x < manchesterData.size()) {
            x = x + jumpSamples;

            // Ensure we don't go out of bounds
            if (x >= manchesterData.size()) break;

            bool startState = manchesterData[x];
            while (x < manchesterData.size() && manchesterData[x] == startState)
            {
                x++;
            }

            if (x < manchesterData.size()) {
                if (manchesterData[x - 1] == false && manchesterData[x] == true) {
                    // 01 transition
                    result = (result << 1) + 1;
                }
                if (manchesterData[x - 1] == true && manchesterData[x] == false) {
                    // 10 transition
                    result = result << 1;
                }
                decodeCount++;
            }
        }
    }

    // We must have 24-bits if the decode was successful
    if (decodeCount != 24) {
        if (decodeCount == 0) qDebug() << "VbiDecoder::manchesterDecoder(): No VBI data found in the field line";
        else qDebug() << "VbiDecoder::manchesterDecoder(): Manchester decode failed!  Only got" << decodeCount << "bits";
        result = 0;
    }

    return result;
}

// Private method to get the map of transitions across the sample and reject noise
QVector<bool> VbiDecoder::getTransitionMap(QByteArray lineData, qint32 zcPoint)
{
    // First read the data into a boolean array using debounce to remove transition noise
    bool previousState = false;
    bool currentState = false;
    qint32 debounce = 0;
    QVector<bool> manchesterData;

    qint32 manchesterPointer = 0;
    for (qint32 xPoint = 0; xPoint < lineData.size(); xPoint += 2) {
        qint32 pixelValue = (static_cast<uchar>(lineData[xPoint + 1]) * 256) + static_cast<uchar>(lineData[xPoint]);
        if (pixelValue > zcPoint) currentState = true; else currentState = false;

        if (currentState != previousState) debounce++;

        if (debounce > 3) {
            debounce = 0;
            previousState = currentState;
        }

        manchesterData.append(previousState);
        manchesterPointer++;
    }

    return manchesterData;
}
