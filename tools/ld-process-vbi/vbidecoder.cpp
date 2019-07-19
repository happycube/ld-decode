/************************************************************************

    vbidecoder.cpp

    ld-process-vbi - VBI and IEC NTSC specific processor for ld-decode
    Copyright (C) 2018-2019 Simon Inns

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
#include "decoderpool.h"

VbiDecoder::VbiDecoder(QAtomicInt& _abort, DecoderPool& _decoderPool, QObject *parent)
    : QThread(parent), abort(_abort), decoderPool(_decoderPool)
{

}

// Thread main processing method
void VbiDecoder::run()
{
    qint32 fieldNumber;

    // Input data buffers
    QByteArray sourceFieldData;
    LdDecodeMetaData::Field fieldMetadata;
    LdDecodeMetaData::VideoParameters videoParameters;

    while(!abort) {
        // Get the next field to process from the input file
        if (!decoderPool.getInputField(fieldNumber, sourceFieldData, fieldMetadata, videoParameters)) {
            // No more input fields -- exit
            break;
        }

        FmCode fmCode;
        FmCode::FmDecode fmDecode;
        bool isWhiteFlag = false;
        WhiteFlag whiteFlag;

        if (fieldMetadata.isFirstField) qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(first)";
        else  qDebug() << "VbiDecoder::process(): Getting metadata for field" << fieldNumber << "(second)";

        // Determine the 16-bit zero-crossing point
        qint32 zcPoint = videoParameters.white16bIre - videoParameters.black16bIre;

        // Get the VBI data from the field lines (we only read field lines 10-18, so the real field line number is -9)
        qDebug() << "VbiDecoder::process(): Getting field-lines for field" << fieldNumber;
        fieldMetadata.vbi.vbiData[0] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 16 - 9, videoParameters), zcPoint, videoParameters);
        fieldMetadata.vbi.vbiData[1] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 17 - 9, videoParameters), zcPoint, videoParameters);
        fieldMetadata.vbi.vbiData[2] = manchesterDecoder(getActiveVideoLine(&sourceFieldData, 18 - 9, videoParameters), zcPoint, videoParameters);

        // Show the VBI data as hexadecimal (for every 1000th field)
        if (fieldNumber % 1000 == 0) {
            qInfo() << "Processing field" << fieldNumber;
        }

        // Translate the VBI data into a decoded VBI object
        fieldMetadata.vbi = translateVbi(fieldMetadata.vbi.vbiData[0], fieldMetadata.vbi.vbiData[1], fieldMetadata.vbi.vbiData[2]);

        // Process NTSC specific data if source type is NTSC
        if (!videoParameters.isSourcePal) {
            // Get the 40-bit FM coded data from the field lines
            fmDecode = fmCode.fmDecoder(getActiveVideoLine(&sourceFieldData, 10 - 9, videoParameters), videoParameters);

            // Get the white flag from the field lines
            isWhiteFlag = whiteFlag.getWhiteFlag(getActiveVideoLine(&sourceFieldData, 11 - 9, videoParameters), videoParameters);

            // Update the metadata
            if (fmDecode.receiverClockSyncBits != 0) {
                fieldMetadata.ntsc.isFmCodeDataValid = true;
                fieldMetadata.ntsc.fmCodeData = static_cast<qint32>(fmDecode.data);
                if (fmDecode.videoFieldIndicator == 1) fieldMetadata.ntsc.fieldFlag = true;
                else fieldMetadata.ntsc.fieldFlag = false;
            } else {
                fieldMetadata.ntsc.isFmCodeDataValid = false;
                fieldMetadata.ntsc.fmCodeData = -1;
                fieldMetadata.ntsc.fieldFlag = false;
            }

            fieldMetadata.ntsc.whiteFlag = isWhiteFlag;
            fieldMetadata.ntsc.inUse = true;
        }

        // Update the metadata for the field
        fieldMetadata.vbi.inUse = true;

        // Write the result to the output metadata
        if (!decoderPool.setOutputField(fieldNumber, fieldMetadata)) {
            abort = true;
            break;
        }
    }
}

// Private method to translate the values of the VBI lines into VBI data
LdDecodeMetaData::Vbi VbiDecoder::translateVbi(qint32 vbi16, qint32 vbi17, qint32 vbi18)
{
    LdDecodeMetaData::Vbi vbi;

    // Default VBI
    vbi.inUse = false;
    vbi.vbiData.resize(3);
    vbi.vbiData[0] = vbi16;
    vbi.vbiData[1] = vbi17;
    vbi.vbiData[2] = vbi18;
    vbi.type = LdDecodeMetaData::VbiDiscTypes::unknownDiscType;
    vbi.userCode = "";
    vbi.picNo = -1;
    vbi.chNo = -1;
    vbi.clvHr = -1;
    vbi.clvMin = -1;
    vbi.clvSec = -1;
    vbi.clvPicNo = -1;
    vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
    vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;

    // Default VBI Flags
    vbi.leadIn = false;
    vbi.leadOut = false;
    vbi.picStop = false;
    vbi.cx = false;
    vbi.size = false;
    vbi.side = false;
    vbi.teletext = false;
    vbi.dump = false;
    vbi.fm = false;
    vbi.digital = false;
    vbi.parity = false;
    vbi.copyAm2 = false;
    vbi.standardAm2 = false;

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
        if (vbi.picNo <= 0 && vbi.picNo >= 80000) {
            qDebug() << "VbiDecoder::translateVbi(): VBI picture number is" << vbi.picNo << "(out of range - set to invalid!)";
            vbi.picNo = -1;
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
    // Note: The allowed chapter number range is 0 to 79
    quint32 bcdChapterNumber = 80;

    if ( (vbi17 & 0xF00FFF) == 0x800DDD ) {
        bcdChapterNumber = (vbi17 & 0x07F000) >> 12;
    } else if ( (vbi18 & 0xF00FFF) == 0x800DDD ) {
        bcdChapterNumber = (vbi18 & 0x07F000) >> 12;
    }

    if (bcdChapterNumber < 80) {
        // Peform BCD to integer conversion:
        vbi.chNo =
                (   10 * ((bcdChapterNumber & 0x000F0) / 16)) +
                (        ((bcdChapterNumber & 0x0000F)));

        qDebug() << "VbiDecoder::translateVbi(): VBI Chapter number is" << vbi.chNo;
    } else {
        qDebug() << "VbiDecoder::translateVbi(): VBI Chapter number not found";
    }

    // IEC 60857-1986 - 10.1.6 Programme time code --------------------------------------------------------------------

    bool clvProgrammeTimeCodeAvailable = false;
    // Check for programme time code on lines 17 and 18
    if ( (vbi17 & 0xF0FF00) == 0xF0DD00 ) {
        vbi.clvHr = (vbi17 & 0x0F0000) >> 16;
        vbi.clvMin = (vbi17 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    } else if ( (vbi18 & 0xF0FF00) == 0xF0DD00 ) {
        vbi.clvHr = (vbi18 & 0x0F0000) >> 16;
        vbi.clvMin = (vbi18 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    }

    if (clvProgrammeTimeCodeAvailable) {
        // Perform BCD conversion
        vbi.clvHr =
                (   10 * ((vbi.clvHr & 0x000F0) / 16)) +
                (        ((vbi.clvHr & 0x0000F)));
        vbi.clvMin =
                (   10 * ((vbi.clvMin & 0x000F0) / 16)) +
                (        ((vbi.clvMin & 0x0000F)));

        // Set the type to CLV for the field as well
        vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;

        qDebug() << "VbiDecoder::translateVbi(): VBI CLV programme time code is" <<
                    vbi.clvHr << "hours," <<
                    vbi.clvMin << "minutes";
    }

    // IEC 60857-1986 - 10.1.7 Constant linear velocity code ----------------------------------------------------------

    // Check for CLV code on line 17 (note: this will be overwritten later if a CLV time code is found)
    vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;

    if ( vbi17 == 0x87FFFF ) {
        vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;
    } else vbi.type = LdDecodeMetaData::VbiDiscTypes::cav;

    // IEC 60857-1986 - 10.1.8 Programme status code ------------------------------------------------------------------

    // Check for programme status code on line 16
    qint32 statusCode = 0;
    if (((vbi16 & 0xFFF000) == 0x8DC000) || ((vbi16 & 0xFFF000) == 0x8BA000)) {
        statusCode = vbi16;
    }

    if (statusCode != 0) {
        // Programme status code is available, decode it...
        // CX sound on or off?
        if ((statusCode & 0x0FF000) == 0x0DC000) {
            qDebug() << "VbiDecoder::translateVbi(): VBI CX sound is on";
            vbi.cx = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI CX sound is off";
            vbi.cx = false;
        }

        // Get the x3, x4 and x5 parameters
        quint32 x3 = (statusCode & 0x000F00) >> 8;
        quint32 x4 = (statusCode & 0x0000F0) >> 4;
        quint32 x5 = (statusCode & 0x00000F);

        if (parity(x4, x5)) {
            vbi.parity = true;
            qDebug() << "VbiDecoder::translateVbi(): VBI Programme status parity check passed";
        } else {
            vbi.parity = false;
            qDebug() << "VbiDecoder::translateVbi(): VBI Programme status parity check failed - Probably an ammendment2 VBI";
        }

        // Get the disc size (12 inch or 8 inch) from x31
        if ((x3 & 0x08) == 0x08) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc is 8 inch";
            vbi.size = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc is 12 inch";
            vbi.size = true;
        }

        // Get the disc side (first or second) from x32
        if ((x3 & 0x04) == 0x04) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc side 2";
            vbi.side = false;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Laserdisc side 1";
            vbi.side = true;
        }

        // Get the teletext presence (present or not present) from x33
        if ((x3 & 0x02) == 0x02) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Disc contains teletext";
            vbi.teletext = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Disc does not contain teletext";
            vbi.teletext = false;
        }

        // Get the analogue/digital video flag from x42
        if ((x4 & 0x04) == 0x04) {
            qDebug() << "VbiDecoder::translateVbi(): VBI Video data is digital";
            vbi.digital = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI Video data is analogue";
            vbi.digital = false;
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
            vbi.dump = false;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 0 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = stereo";
            break;
        case 1:
            vbi.dump = false;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 1 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = mono";
            break;
        case 2:
            vbi.dump = false;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 2 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = futureUse";
            break;
        case 3:
            vbi.dump = false;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 3 - isProgrammeDump = false - isFmFmMultiplex = false - soundMode = bilingual";
            break;
        case 4:
            vbi.dump = false;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 4 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = stereo_stereo";
            break;
        case 5:
            vbi.dump = false;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 5 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = stereo_bilingual";
            break;
        case 6:
            vbi.dump = false;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::crossChannelStereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 6 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = crossChannelStereo";
            break;
        case 7:
            vbi.dump = false;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 7 - isProgrammeDump = false - isFmFmMultiplex = true - soundMode = bilingual_bilingual";
            break;
        case 8:
            vbi.dump = true;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 8 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 9:
            vbi.dump = true;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 9 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 10:
            vbi.dump = true;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 10 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = futureUse";
            break;
        case 11:
            vbi.dump = true;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 11 - isProgrammeDump = true - isFmFmMultiplex = false - soundMode = mono_dump";
            break;
        case 12:
            vbi.dump = true;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 12 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = stereo_dump";
            break;
        case 13:
            vbi.dump = true;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 13 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = stereo_dump";
            break;
        case 14:
            vbi.dump = true;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 14 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = bilingual_dump";
            break;
        case 15:
            vbi.dump = true;
            vbi.fm = true;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::bilingual_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI audio status 15 - isProgrammeDump = true - isFmFmMultiplex = true - soundMode = bilingual_dump";
            break;
        default:
            qDebug() << "VbiDecoder::translateVbi(): VBI - Invalid audio status code!";
            vbi.dump = false;
            vbi.fm = false;
            vbi.soundMode = LdDecodeMetaData::VbiSoundModes::stereo;
        }
    }

    // IEC 60857-1986 - 10.1.8 Programme status code (IEC Amendment 2) ------------------------------------------------

    // Check for programme status code on line 16
    qint32 statusCodeAm2 = 0;
    if (((vbi16 & 0xFFF000) == 0x8DC000) || ((vbi16 & 0xFFF000) == 0x8BA000)) {
        statusCodeAm2 = vbi16;
    }

    if (statusCodeAm2 != 0) {
        // Programme status code is available, decode it...
        // Only fields specific to Am2 will be decoded

        // Get the x3, x4 and x5 parameters
        quint32 x3 = (statusCode & 0x000F00) >> 8;
        quint32 x4 = (statusCode & 0x0000F0) >> 4;
        //quint32 x5 = (statusCode & 0x00000F);

        // Get the copy/no copy flag from x34
        if ((x3 & 0x01) == 0x01) {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Copy permitted";
            vbi.copyAm2 = true;
        } else {
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Copy prohibited";
            vbi.copyAm2 = false;
        }

        // The audio channel status is given by x41, x42, x43 and x44 combined
        // (giving 16 possible audio status results)
        quint32 audioStatus = 0;
        if ((x4 & 0x08) == 0x08) audioStatus += 8; // X41 X42 X43 X44
        if ((x4 & 0x04) == 0x04) audioStatus += 4;
        if ((x4 & 0x02) == 0x02) audioStatus += 2;
        if ((x4 & 0x01) == 0x01) audioStatus += 1;
        qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) Programme status code - audio status is" << audioStatus;

        // Configure according to the audio status code
        switch(audioStatus) {
        case 0:
            vbi.standardAm2 = true;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 0 - isVideoSignalStandard = true - soundMode = stereo";
            break;
        case 1:
            vbi.standardAm2 = true;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 1 - isVideoSignalStandard = true - soundMode = mono";
            break;
        case 2:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 2 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 3:
            vbi.standardAm2 = true;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::bilingual;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 3 - isVideoSignalStandard = true - soundMode = bilingual";
            break;
        case 4:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 4 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 5:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 5 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 6:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 6 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 7:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 7 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 8:
            vbi.standardAm2 = true;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::mono_dump;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 8 - isVideoSignalStandard = true - soundMode = mono_dump";
            break;
        case 9:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 9 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 10:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 10 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 11:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 11 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 12:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 12 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 13:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 13 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 14:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 14 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        case 15:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::futureUse;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) audio status 15 - isVideoSignalStandard = false - soundMode = futureUse";
            break;
        default:
            vbi.standardAm2 = false;
            vbi.soundModeAm2 = LdDecodeMetaData::VbiSoundModes::stereo;
            qDebug() << "VbiDecoder::translateVbi(): VBI (Am2) - Invalid audio status code!";
        }
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
        qDebug() << "VbiDecoder::translateVbi(): VBI user code is" << vbi.userCode;
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

        vbi.clvSec = ((x1 - 10) * 10) + x3;
        vbi.clvPicNo = (x4  * 10) + x5;

        // Set the type to CLV for the field as well
        vbi.type = LdDecodeMetaData::VbiDiscTypes::clv;

        qDebug() << "VbiDecoder::translateVbi(): VBI CLV picture number is" <<
                    vbi.clvSec << "seconds," <<
                    vbi.clvPicNo << "picture number";
    }

    // Output the disc type here, as the CLV time-code determination can change it
    if (vbi.type == LdDecodeMetaData::VbiDiscTypes::cav) {
        qDebug() << "VbiDecoder::translateVbi(): VBI Disc type is CAV";
        qDebug() << "VbiDecoder::translateVbi(): VBI picture number is" << vbi.picNo;
    } else {
        qDebug() << "VbiDecoder::translateVbi(): VBI Disc type is CLV";

        // Invalidate the CAV picture number
        vbi.picNo = -1;
    }

    return vbi;
}

// Private method to verifiy parity
bool VbiDecoder::parity(quint32 x4, quint32 x5)
{
    // X51 is the parity with X41, X42 and X44
    // X52 is the parity with X41, X43 and X44
    // X53 is the parity with X42, X43 and X44

    // Get the parity bits from X5
    qint32 x51, x52, x53;
    if ((x5 & 0x8) == 0x8) x51 = 1; else x51 = 0;
    if ((x5 & 0x4) == 0x4) x52 = 1; else x52 = 0;
    if ((x5 & 0x2) == 0x2) x53 = 1; else x53 = 0;

    // Get the data bits from X4
    qint32 x41, x42, x43, x44;
    if ((x4 & 0x8) == 0x8) x41 = 1; else x41 = 0;
    if ((x4 & 0x4) == 0x4) x42 = 1; else x42 = 0;
    if ((x4 & 0x2) == 0x2) x43 = 1; else x43 = 0;
    if ((x4 & 0x1) == 0x1) x44 = 1; else x44 = 0;

    // Count the data bits according to the IEC specification
    qint32 x51count = x41 + x42 + x44;
    qint32 x52count = x41 + x43 + x44;
    qint32 x53count = x42 + x43 + x44;

    // Check if the parity is correct
    bool x51p = false;
    bool x52p = false;
    bool x53p = false;

    if ((((x51count % 2) == 0) && (x51 == 0)) || (((x51count % 2) != 0) && (x51 != 0))) x51p = true;
    if ((((x52count % 2) == 0) && (x51 == 0)) || (((x52count % 2) != 0) && (x52 != 0))) x52p = true;
    if ((((x53count % 2) == 0) && (x51 == 0)) || (((x53count % 2) != 0) && (x53 != 0))) x53p = true;

    if (x51p && x52p && x53p) return true;
    return false;
}

// Private method to get a single scanline of greyscale data
QByteArray VbiDecoder::getActiveVideoLine(QByteArray *sourceField, qint32 fieldLine,
                                        LdDecodeMetaData::VideoParameters videoParameters)
{
    // Range-check the scan line
    if (fieldLine > videoParameters.fieldHeight || fieldLine < 1) {
        qWarning() << "Cannot generate field-line data, line number is out of bounds! Scan line =" << fieldLine;
        return QByteArray();
    }

    qint32 startPointer = ((fieldLine - 1) * videoParameters.fieldWidth * 2) + (videoParameters.activeVideoStart * 2);
    qint32 length = (videoParameters.activeVideoEnd - videoParameters.activeVideoStart) * 2;

    return sourceField->mid(startPointer, length);
}

// Private method to read a 24-bit biphase coded signal (manchester code) from a field line
qint32 VbiDecoder::manchesterDecoder(QByteArray lineData, qint32 zcPoint,
                                     LdDecodeMetaData::VideoParameters videoParameters)
{
    qint32 result = 0;
    QVector<bool> manchesterData = getTransitionMap(lineData, zcPoint);

    // Get the number of samples for 1.5us
    qreal fJumpSamples = (videoParameters.sampleRate / 1000000) * 1.5;
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
