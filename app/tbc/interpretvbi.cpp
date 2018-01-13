/************************************************************************

    interpretvbi.cpp

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

#include "interpretvbi.h"

InterpretVbi::InterpretVbi(quint32 line16, quint32 line17, quint32 line18)
{
    // Set default values for VBI
    discType = unknownType;
    leadIn = false;
    leadOut = false;
    userCodeAvailable = false;
    userCode.clear();
    pictureNumberAvailable = false;
    pictureNumber = 0;
    pictureStopCode = false;
    chapterNumberAvailable = false;
    chapterNumber = 0;
    clvProgrammeTimeCodeAvailable = false;
    clvProgrammeTimeCode.hours = 0;
    clvProgrammeTimeCode.minutes = 0;
    programmeStatusCodeAvailable = false;

    // Check for lead-in on line 17 or 18
    if (((line17 & 0x88FFFF) == 0x88FFFF) ||
            ((line18 & 0x88FFFF) == 0x88FFFF)) {
        qDebug() << "VBI Lead-in";
        leadIn = true;
    }

    // Check for lead-out on line 17 or 18
    if (((line17 & 0x80EEEE) == 0x80EEEE) ||
            ((line18 & 0x80EEEE) == 0x80EEEE)) {
        qDebug() << "VBI Lead-out";
        leadIn = true;
    }

    // If lead-in or lead-out, check for user code
    if(leadIn || leadOut) {
        if ((line16 & 0x80D000) == 0x80D000) {
            // User code found
            quint32 x1 = (line16 & 0x0F0000) >> 16;
            quint32 x3x4x5 = (line16 & 0x000FFF);

            // x1 should be 0x00-0x07, x3-x5 are 0x00-0x0F
            if (x1 > 7) qDebug() << "VBI invalid user code, X1 is > 7";

            // Add the two results together to get the user code
            userCode = QString::number(x1, 16).toUpper() + QString::number(x3x4x5, 16).toUpper();
            userCodeAvailable = true;
            qDebug() << "VBI user code is" << userCode;
        } else {
            userCodeAvailable = false;
        }
    }

    // If a program time code or CLV code is present on line 17
    // this is a CLV disc, otherwise assume its CAV
    if (((line17 & 0xF0DD00) == 0xF0DD00) ||
            ((line17 & 0x87FFFF) == 0xF87FFFF)) {
        qDebug() << "VBI Disc type is CLV";
        discType = clv;
    } else {
        // The IEC spec is unclear if this is a bad assumption
        // during lead-in or lead-out but for now, this is how it is
        qDebug() << "VBI Disc type is CAV";
        discType = cav;
    }

    // If discType is CAV check for picture number on line 17
    if ((discType == cav) && ((line17 & 0xF00000) == 0xF00000)) {
        pictureNumber = line17 & 0x0FFFFF;
        pictureNumberAvailable = true;
    }

    // If discType is CAV check for picture number on line 18
    if ((discType == cav) && ((line18 & 0xF00000) == 0xF00000)) {
        pictureNumber = line18 & 0x0FFFFF;
        pictureNumberAvailable = true;
    }

    if (pictureNumberAvailable) {
        if (pictureNumber > 0 && pictureNumber < 80000) {
            qDebug() << "VBI picture number is" << pictureNumber;
        } else {
            qDebug() << "VBI picture number is" << pictureNumber << "(out of range!)";
        }
    }

    // If discType is CAV check for picture stop code on line 16
    if ((discType == cav) && ((line16 & 0x82CFFF) == 0x82CFFF)) {
        pictureStopCode = true;
    }

    // If discType is CAV check for picture stop code on line 17
    if ((discType == cav) && ((line17 & 0x82CFFF) == 0x82CFFF)) {
        pictureStopCode = true;
    }

    if (pictureStopCode) qDebug() << "VBI Picture stop code flagged";

    // If discType is CAV check for chapter number on line 17
    if ((discType == cav) && ((line17 & 0x800DDD) == 0x800DDD)) {
        chapterNumber = (line17 & 0x0FF000) >> 12;
        chapterNumberAvailable = true;
    }

    // If disc type is CAV or CLV check for chapter number on line 18
    if ((line18 & 0x800DDD) == 0x800DDD) {
        chapterNumber = (line18 & 0x0FF000) >> 12;
        chapterNumberAvailable = true;
    }

    if (chapterNumberAvailable) qDebug() << "VBI Chapter number is" << chapterNumber;

    // If disc type is CLV check for programme time code on line 17
    if ((discType == clv) && ((line17 & 0xF0DD00) == 0xF0DD00)) {
        clvProgrammeTimeCode.hours = (line17 & 0x0F0000) >> 16;
        clvProgrammeTimeCode.minutes = (line17 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    }

    // If disc type is CLV check for programme time code on line 18
    if ((discType == clv) && ((line18 & 0xF0DD00) == 0xF0DD00)) {
        clvProgrammeTimeCode.hours = (line18 & 0x0F0000) >> 16;
        clvProgrammeTimeCode.minutes = (line18 & 0x0000FF);
        clvProgrammeTimeCodeAvailable = true;
    }

    if (clvProgrammeTimeCodeAvailable) {
        qDebug() << "VBI CLV programme time code is" <<
                    clvProgrammeTimeCode.hours << "hours," <<
                    clvProgrammeTimeCode.minutes << "minutes";
    }

    // If discType is CAV or CLV check for programme status code on line 16
    if (((line16 & 0x8DC000) == 0x8DC000) || ((line16 & 0x8BA000) == 0x8BA000)) {
        // Programme status code is available, decode it...
        programmeStatusCodeAvailable = true;

        // CX sound on or off?
        if ((line16 & 0x0DC000) == 0x0DC000) programmeStatusCode.isCxOn = true;
        else programmeStatusCode.isCxOn = false;

        // Get the x3, x4 and x5 parameters
        quint32 x3 = (line16 & 0x000F00) >> 8;
        quint32 x4 = (line16 & 0x0000F0) >> 4;
        //quint32 x5 = (line16 & 0x00000F);

        // Get the disc size (12 inch or 8 inch) from x3 bit 1
        if ((x3 & 0x01) == 0x01) programmeStatusCode.isTwelveInchDisk = false;
        else programmeStatusCode.isTwelveInchDisk = true;

        // Get the disc side (first or second) from x3 bit 2
        if ((x3 & 0x02) == 0x02) programmeStatusCode.isFirstSide = false;
        else programmeStatusCode.isFirstSide = true;

        // Get the teletext presence (present or not present) from x3 bit 3
        if ((x3 & 0x04) == 0x04) programmeStatusCode.isTeletextPresent = true;
        else programmeStatusCode.isTeletextPresent = false;

        // Get the analogue/digital video flag from x4 bit 2
        if ((x4 & 0x02) == 0x02) programmeStatusCode.isVideoDigital = true;
        else programmeStatusCode.isVideoDigital = false;

        // The audio channel status is given by x4 bit 1, x3 bit 4, x4 bit 3 and x4 bit 4 combined
        // (giving 16 possible audio status results)
        quint32 audioStatus = 0;
        if ((x4 & 0x01) == 0x01) audioStatus += 1;
        if ((x4 & 0x04) == 0x04) audioStatus += 2;
        if ((x3 & 0x08) == 0x08) audioStatus += 4;
        if ((x4 & 0x01) == 0x01) audioStatus += 8;
        qDebug() << "VBI Programme status code - audio status is" << audioStatus;

        // TODO: Implement hamming code parity check/correction...
        programmeStatusCode.isParityCorrect = false;

        // Configure according to the audio status code
        switch(audioStatus) {
        case 0:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = stereo;
            break;
        case 1:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = mono;
            break;
        case 2:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = futureUse;
            break;
        case 3:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = bilingual;
            break;
        case 4:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = stereo_stereo;
            break;
        case 5:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = stereo_bilingual;
            break;
        case 6:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = crossChannelStereo;
            break;
        case 7:
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = bilingual_bilingual;
            break;
        case 8:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = mono_dump;
            break;
        case 9:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = mono_dump;
            break;
        case 10:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = futureUse;
            break;
        case 11:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = mono_dump;
            break;
        case 12:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = stereo_dump;
            break;
        case 13:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = stereo_dump;
            break;
        case 14:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = bilingual_dump;
            break;
        case 15:
            programmeStatusCode.isProgrammeDump = true;
            programmeStatusCode.isFmFmMultiplex = true;
            programmeStatusCode.soundMode = bilingual_dump;
            break;
        default:
            qDebug() << "VBI - Invalid audio status code!";
            programmeStatusCode.isProgrammeDump = false;
            programmeStatusCode.isFmFmMultiplex = false;
            programmeStatusCode.soundMode = stereo;
        }
    }

    // If discType is CLV check for CLV picture number on line 16
    if ((discType == clv) && ((line16 & 0x80E000) == 0x80E000)) {
        clvPictureNumberAvailable = true;

        // Get the x1, x3, x4 and x5 parameters
        quint32 x1 = (line16 & 0x0F0000) >> 16;
        quint32 x3 = (line16 & 0x000F00) >> 8;
        quint32 x4x5 = (line16 & 0x0000FF);

        clvPictureNumber.seconds = (x1 * 16) + x3;  // Convert hex to decimal
        clvPictureNumber.pictureNumber = x4x5;

        qDebug() << "VBI CLV picture number is" <<
                    clvPictureNumber.seconds << "seconds," <<
                    clvPictureNumber.pictureNumber << "picture number";
    }
}

// Gets
InterpretVbi::DiscTypes InterpretVbi::getDiscType(void)
{
    return discType;
}

quint32 InterpretVbi::getPictureNumber(void)
{
    return pictureNumber;
}

InterpretVbi::ClvPictureNumber InterpretVbi::getClvPictureNumber(void)
{
    return clvPictureNumber;
}

quint32 InterpretVbi::getChapterNumber(void)
{
    return chapterNumber;
}

InterpretVbi::ProgrammeStatusCode InterpretVbi::getProgrammeStatusCode(void)
{
    return programmeStatusCode;
}

InterpretVbi::ClvProgrammeTimeCode InterpretVbi::getClvProgrammeTimeCode(void)
{
    return clvProgrammeTimeCode;
}

QString InterpretVbi::getUserCode(void)
{
    return userCode;
}

// Tests
bool InterpretVbi::isLeadIn(void)
{
    return leadIn;
}

bool InterpretVbi::isLeadOut(void)
{
    return leadOut;
}

bool InterpretVbi::isUserCodeAvailable(void)
{
    return userCodeAvailable;
}

bool InterpretVbi::isPictureNumberAvailable(void)
{
    return pictureNumberAvailable;
}

bool InterpretVbi::isClvPictureNumberAvailable(void)
{
    return clvPictureNumberAvailable;
}

bool InterpretVbi::isPictureStopRequested(void)
{
    return pictureStopCode;
}

bool InterpretVbi::isChapterNumberAvailable(void)
{
    return chapterNumberAvailable;
}

bool InterpretVbi::isProgrammeStatusCodeAvailable(void)
{
    return programmeStatusCodeAvailable;
}

bool InterpretVbi::isClvProgrammeTimeCodeAvailable(void)
{
    return clvProgrammeTimeCodeAvailable;
}
