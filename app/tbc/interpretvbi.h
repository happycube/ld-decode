/************************************************************************

    interpretvbi.h

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

#ifndef INTERPRETVBI_H
#define INTERPRETVBI_H

#include <QCoreApplication>
#include <QDebug>

class InterpretVbi
{
public:
    InterpretVbi(quint32 line16, quint32 line17, quint32 line18);

    // Disc type
    enum DiscTypes {
        unknownType,
        clv,
        cav
    };

    // Sound modes
    enum SoundModes {
        stereo,
        mono,
        audioSubCarriersOff,
        bilingual,
        stereo_stereo,
        stereo_bilingual,
        crossChannelStereo,
        bilingual_bilingual,
        mono_dump,
        stereo_dump,
        bilingual_dump,
        futureUse
    };

    typedef struct {
        quint32 hours;
        quint32 minutes;
    } ProgrammeTimeCode;

    typedef struct {
        quint32 hours;
        quint32 minutes;
    } ClvProgrammeTimeCode;

    typedef struct {
        bool isCxOn;                // True = CX on, false = CX off
        bool isTwelveInchDisk;      // True = 12" disc, false = 8" disc
        bool isFirstSide;           // True = first side, false = second side
        bool isTeletextPresent;     // True = teletext present, false = teletext not present
        bool isProgrammeDump;       // True = programme dump on, false = programme dump off
        bool isFmFmMultiplex;       // True = FM-FM Multiplex on, false = FM-FM Multiplex off
        bool isVideoDigital;        // True = digital video, false = analogue video
        SoundModes soundMode;       // The sound mode (see IEC spec)
        bool isParityCorrect;       // True = status code had valid parity, false = status code is invalid
    } ProgrammeStatusCode;

    typedef struct {
        quint32 seconds;
        quint32 pictureNumber;
    } ClvPictureNumber;

    // Gets
    DiscTypes getDiscType(void);
    quint32 getPictureNumber(void);
    ClvPictureNumber getClvPictureNumber(void);
    quint32 getChapterNumber(void);
    ProgrammeStatusCode getProgrammeStatusCode(void);
    ClvProgrammeTimeCode getClvProgrammeTimeCode(void);
    QString getUserCode(void);

    // Tests
    bool isLeadIn(void);
    bool isLeadOut(void);
    bool isUserCodeAvailable(void);
    bool isPictureNumberAvailable(void);
    bool isClvPictureNumberAvailable(void);
    bool isPictureStopRequested(void);
    bool isChapterNumberAvailable(void);
    bool isProgrammeStatusCodeAvailable(void);
    bool isClvProgrammeTimeCodeAvailable(void);

private:
    DiscTypes discType;
    bool leadIn;
    bool leadOut;

    bool userCodeAvailable;

    QString userCode;

    bool pictureNumberAvailable;
    quint32 pictureNumber;

    bool pictureStopCode;

    bool chapterNumberAvailable;
    quint32 chapterNumber;

    bool clvProgrammeTimeCodeAvailable;
    ClvProgrammeTimeCode clvProgrammeTimeCode;

    bool programmeStatusCodeAvailable;
    ProgrammeStatusCode programmeStatusCode;

    bool clvPictureNumberAvailable;
    ClvPictureNumber clvPictureNumber;
};

#endif // INTERPRETVBI_H
