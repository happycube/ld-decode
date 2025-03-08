/************************************************************************

    subcode.cpp

    EFM-library - Convert subcode data to FrameMetadata and back
    Copyright (C) 2025 Simon Inns

    This file is part of EFM-Tools.

    This is free software: you can redistribute it and/or
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

#include "subcode.h"

// Takes 98 bytes of subcode data and returns a FrameMetadata object
SectionMetadata Subcode::fromData(const QByteArray &data)
{
    // Ensure the data is 98 bytes long
    if (data.size() != 98) {
        qFatal("Subcode::fromData(): Data size of %d does not match 98 bytes", data.size());
    }

    // Extract the p-channel data and q-channel data
    QByteArray pChannelData;
    QByteArray qChannelData;
    pChannelData.resize(12);
    qChannelData.resize(12);

    // Note: index 0 and 1 are sync0 and sync1 bytes
    // so we get 96 bits of data per channel from 98 bytes input
    for (int index = 2; index < data.size(); ++index) {
        setBit(pChannelData, index - 2, data[index] & 0x80);
        setBit(qChannelData, index - 2, data[index] & 0x40);
    }

    // Create the SectionMetadata object
    SectionMetadata sectionMetadata;

    // Set the p-channel (p-channel is just repeating flag)
    // For correction purposes we will count the number of 0s and 1s
    // and set the flag to the majority value
    int oneCount = 0;
    for (int index = 2; index < pChannelData.size(); ++index) {
        // Count the number of bits set to 1 in pChannelData[index]
        oneCount += countBits(static_cast<quint8>(pChannelData[index]));
    }

    // if (oneCount != 96 && oneCount != 0) {
    //     if (m_showDebug) {
    //         qDebug() << "Subcode::fromData(): P channel data contains" << 96-oneCount << "zeros and"
    //                  << oneCount << "ones - indicating some p-channel corruption"; 
    //     }
    // }

    if (oneCount > (96/2)) {
        sectionMetadata.setPFlag(true);
    } else {
        sectionMetadata.setPFlag(false);
    }

    // Set the q-channel
    // If the q-channel CRC is not valid, attempt to repair the data
    if (!isCrcValid(qChannelData))
        sectionMetadata.setRepaired(repairData(qChannelData));

    if (isCrcValid(qChannelData)) {
        // Set the q-channel data from the subcode data

        // Get the address and control nybbles
        quint8 controlNybble = qChannelData[0] >> 4;
        quint8 modeNybble = qChannelData[0] & 0x0F;

        // Set the q-channel mode
        switch (modeNybble) {
        case 0x0:
            // IEC 60908 17.5.4 says to treat this as Q-mode 1
            sectionMetadata.setQMode(SectionMetadata::QMode1);
            break;
        case 0x1:
            sectionMetadata.setQMode(SectionMetadata::QMode1);
            break;
        case 0x2:
            sectionMetadata.setQMode(SectionMetadata::QMode2);
            break;
        case 0x3:
            sectionMetadata.setQMode(SectionMetadata::QMode3);
            break;
        case 0x4:
            sectionMetadata.setQMode(SectionMetadata::QMode4);
            break;
        default:
            if (m_showDebug)
                qDebug() << "Subcode::fromData(): Q channel data is:" << qChannelData.toHex();
            qFatal("Subcode::fromData(): Invalid Q-mode nybble! Must be 1, 2, 3 or 4 not %d",
                   modeNybble);
        }

        // Set the q-channel control settings
        switch (controlNybble) {
        case 0x0:
            // AUDIO_2CH_NO_PREEMPHASIS_COPY_PROHIBITED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(true);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(true);
            break;
        case 0x1:
            // AUDIO_2CH_PREEMPHASIS_COPY_PROHIBITED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(true);
            sectionMetadata.setPreemphasis(true);
            sectionMetadata.set2Channel(true);
            break;
        case 0x2:
            // AUDIO_2CH_NO_PREEMPHASIS_COPY_PERMITTED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(false);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(true);
            break;
        case 0x3:
            // AUDIO_2CH_PREEMPHASIS_COPY_PERMITTED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(false);
            sectionMetadata.setPreemphasis(true);
            sectionMetadata.set2Channel(true);
            break;
        case 0x4:
            // DIGITAL_COPY_PROHIBITED
            sectionMetadata.setAudio(false);
            sectionMetadata.setCopyProhibited(true);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(true);
            break;
        case 0x6:
            // DIGITAL_COPY_PERMITTED
            sectionMetadata.setAudio(false);
            sectionMetadata.setCopyProhibited(false);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(true);
            break;
        case 0x8:
            // AUDIO_4CH_NO_PREEMPHASIS_COPY_PROHIBITED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(true);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(false);
            break;
        case 0x9:
            // AUDIO_4CH_PREEMPHASIS_COPY_PROHIBITED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(true);
            sectionMetadata.setPreemphasis(true);
            sectionMetadata.set2Channel(false);
            break;
        case 0xA:
            // AUDIO_4CH_NO_PREEMPHASIS_COPY_PERMITTED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(false);
            sectionMetadata.setPreemphasis(false);
            sectionMetadata.set2Channel(false);
            break;
        case 0xB:
            // AUDIO_4CH_PREEMPHASIS_COPY_PERMITTED
            sectionMetadata.setAudio(true);
            sectionMetadata.setCopyProhibited(false);
            sectionMetadata.setPreemphasis(true);
            sectionMetadata.set2Channel(false);
            break;
        default:
            if (m_showDebug)
                qDebug() << "Subcode::fromData(): Q channel data is:" << qChannelData.toHex();
            qFatal("Subcode::fromData(): Invalid control nybble! Must be 0-3, 4-7 or 8-11 not %d",
                   controlNybble);
        }

        if (sectionMetadata.qMode() == SectionMetadata::QMode1
            || sectionMetadata.qMode() == SectionMetadata::QMode4) {
            // Get the track number
            quint8 trackNumber = bcd2ToInt(qChannelData[1]);

            // If the track number is 0, then this is a lead-in frame
            // If the track number is 0xAA, then this is a lead-out frame
            // If the track number is 1-99, then this is a user data frame
            if (trackNumber == 0) {
                sectionMetadata.setSectionType(SectionType(SectionType::LeadIn), 0);
                qDebug() << "Subcode::fromData(): Q-Mode 1/4 has track number 0 - this is a lead-in frame";
            } else if (trackNumber == 0xAA) {
                sectionMetadata.setSectionType(SectionType(SectionType::LeadOut), 0);
                qDebug() << "Subcode::fromData(): Q-Mode 1/4 has track number 0xAA - this is a lead-out frame";
            } else {
                sectionMetadata.setSectionType(SectionType(SectionType::UserData), trackNumber);
            }
            
            // Set the frame time q_data_channel[3-5]
            sectionMetadata.setSectionTime(SectionTime(
                    bcd2ToInt(qChannelData[3]), bcd2ToInt(qChannelData[4]), bcd2ToInt(qChannelData[5])));

            // Set the zero byte q_data_channel[6] - Not used at the moment

            // Set the ap time q_data_channel[7-9]
            sectionMetadata.setAbsoluteSectionTime(SectionTime(
                    bcd2ToInt(qChannelData[7]), bcd2ToInt(qChannelData[8]), bcd2ToInt(qChannelData[9])));
        } else if (sectionMetadata.qMode() == SectionMetadata::QMode2) {
            // Extract the 52 bit UPC/EAN code
            // This is a 13 digit BCD code, so we need to convert it to an integer
            quint64 upc = 0;
            for (int i = 0; i < 13; ++i) {
                upc *= 10;
                upc += bcd2ToInt(qChannelData[i + 1]);
            }
            sectionMetadata.setUpcEanCode(upc);
            if (m_showDebug) {
                // Show the UPC/EAN code as 13 digits padded with leading zeros
                QString upcString = QString::number(upc);
                while (upcString.size() < 13) {
                    upcString = "0" + upcString;
                }
                
                qDebug() << "Subcode::fromData(): Q-Mode 2 has UPC/EAN code of:" << upcString;
            }

            // Only the absolute frame number is included for Q mode 2
            sectionMetadata.setSectionType(SectionType(SectionType::UserData), 1);
            sectionMetadata.setSectionTime(SectionTime(0, 0, 0));
            sectionMetadata.setAbsoluteSectionTime(SectionTime(0, 0, bcd2ToInt(qChannelData[9])));
        } else if (sectionMetadata.qMode() == SectionMetadata::QMode3) {
            // There is no test data for this qmode, so this is untested
            qWarning("Subcode::fromData(): Q-Mode 3 metadata is present on this disc.  This is untested.");
            qFatal("Subcode::fromData(): Please submit this data for testing - ask in Discord/IRC");

            // Only the absolute frame number is included for Q mode 3
            sectionMetadata.setSectionType(SectionType(SectionType::UserData), 1);
            sectionMetadata.setSectionTime(SectionTime(0, 0, 0));
            sectionMetadata.setAbsoluteSectionTime(SectionTime(0, 0, bcd2ToInt(qChannelData[9])));
        } else {
            qFatal("Subcode::fromData(): Invalid Q-mode %d", sectionMetadata.qMode());
        }

        sectionMetadata.setValid(true);
    } else {
        // Set the q-channel data to invalid leaving the rest of
        // the metadata as default values
        if (m_showDebug)
            qDebug() << "Subcode::fromData(): Invalid CRC in Q-channel data - expected:"
                     << QString::number(getQChannelCrc(qChannelData), 16)
                     << "calculated:" << QString::number(calculateQChannelCrc16(qChannelData), 16);

        // Range check the absolute time - as it is potentially corrupt and could be out of range
        qint32 minutes = bcd2ToInt(qChannelData[7]);
        qint32 seconds = bcd2ToInt(qChannelData[8]);
        qint32 frames = bcd2ToInt(qChannelData[9]);

        if (minutes < 0) minutes = 0;
        if (minutes > 59) minutes = 59;
        if (seconds < 0) seconds = 0;
        if (seconds > 59) seconds = 59;
        if (frames < 0) frames = 0;
        if (frames > 74) frames = 74;

        SectionTime badAbsTime = SectionTime(minutes, seconds, frames);
        if (m_showDebug)
            qDebug().noquote() << "Subcode::fromData(): Q channel data is:" << qChannelData.toHex()
                               << "potentially corrupt absolute time is:"
                               << badAbsTime.toString();
        sectionMetadata.setValid(false);
    }

    // Sanity check the track number and frame type
    //
    // If the track number is 0, then this is a lead-in frame
    // If the track number is 0xAA, then this is a lead-out frame
    // If the track number is 1-99, then this is a user data frame
    if (sectionMetadata.trackNumber() == 0
        && sectionMetadata.sectionType().type() != SectionType::LeadIn) {
        if (m_showDebug)
            qDebug("Subcode::fromData(): Track number 0 is only valid for lead-in frames");
    } else if (sectionMetadata.trackNumber() == 0xAA
               && sectionMetadata.sectionType().type() != SectionType::LeadOut) {
        if (m_showDebug)
            qDebug("Subcode::fromData(): Track number 0xAA is only valid for lead-out frames");
    } else if (sectionMetadata.trackNumber() > 99) {
        if (m_showDebug)
            qDebug("Subcode::fromData(): Track number %d is out of range",
                   sectionMetadata.trackNumber());
    }

    if (sectionMetadata.isRepaired()) {
        if (m_showDebug)
            qDebug().noquote()
                    << "Subcode::fromData(): Q-channel repaired for section with absolute time:"
                    << sectionMetadata.absoluteSectionTime().toString()
                    << "track number:" << sectionMetadata.trackNumber()
                    << "and section time:" << sectionMetadata.sectionTime().toString();
    }

    // All done!
    return sectionMetadata;
}

quint8 Subcode::countBits(quint8 byteValue)
{
    quint8 count = 0;
    for (int i = 0; i < 8; ++i) {
        if (byteValue & (1 << i))
            count++;
    }
    return count;
}

// Takes a FrameMetadata object and returns 98 bytes of subcode data
QByteArray Subcode::toData(const SectionMetadata &sectionMetadata)
{
    QByteArray pChannelData(12, 0);
    QByteArray qChannelData(12, 0);

    // Set the p-channel data
    for (int i = 0; i < 12; ++i) {
        if (sectionMetadata.pFlag())
            pChannelData[i] = 0xFF;
        else
            pChannelData[i] = 0x00;
    }

    // Create the control and address nybbles
    quint8 controlNybble = 0;
    quint8 modeNybble = 0;

    switch (sectionMetadata.qMode()) {
    case SectionMetadata::QMode1:
        modeNybble = 0x1; // 0b0001
        break;
    case SectionMetadata::QMode2:
        modeNybble = 0x2; // 0b0010
        break;
    case SectionMetadata::QMode3:
        modeNybble = 0x3; // 0b0011
        break;
    case SectionMetadata::QMode4:
        modeNybble = 0x4; // 0b0100
        break;
    default:
        qFatal("Subcode::toData(): Invalid Q-mode %d", sectionMetadata.qMode());
    }

    bool audio = sectionMetadata.isAudio();
    bool copyProhibited = sectionMetadata.isCopyProhibited();
    bool preemphasis = sectionMetadata.hasPreemphasis();
    bool channels2 = sectionMetadata.is2Channel();

    // These are the valid combinations of control nybble flags
    if (audio && channels2 && !preemphasis && copyProhibited)
        controlNybble = 0x0; // 0b0000 = AUDIO_2CH_NO_PREEMPHASIS_COPY_PROHIBITED
    else if (audio && channels2 && preemphasis && copyProhibited)
        controlNybble = 0x1; // 0b0001 = AUDIO_2CH_PREEMPHASIS_COPY_PROHIBITED
    else if (audio && channels2 && !preemphasis && !copyProhibited)
        controlNybble = 0x2; // 0b0010 = AUDIO_2CH_NO_PREEMPHASIS_COPY_PERMITTED
    else if (audio && channels2 && preemphasis && !copyProhibited)
        controlNybble = 0x3; // 0b0011 = AUDIO_2CH_PREEMPHASIS_COPY_PERMITTED
    else if (!audio && copyProhibited)
        controlNybble = 0x4; // 0b0100 = DIGITAL_COPY_PROHIBITED
    else if (!audio && !copyProhibited)
        controlNybble = 0x6; // 0b0110 = DIGITAL_COPY_PERMITTED
    else if (audio && !channels2 && !preemphasis && copyProhibited)
        controlNybble = 0x8; // 0b1000 = AUDIO_4CH_NO_PREEMPHASIS_COPY_PROHIBITED
    else if (audio && !channels2 && preemphasis && copyProhibited)
        controlNybble = 0x9; // 0b1001 = AUDIO_4CH_PREEMPHASIS_COPY_PROHIBITED
    else if (audio && !channels2 && !preemphasis && !copyProhibited)
        controlNybble = 0xA; // 0b1010 = AUDIO_4CH_NO_PREEMPHASIS_COPY_PERMITTED
    else if (audio && !channels2 && preemphasis && !copyProhibited)
        controlNybble = 0xB; // 0b1011 = AUDIO_4CH_PREEMPHASIS_COPY_PERMITTED
    else {
        qFatal("Subcode::toData(): Invalid control nybble! Must be 0-3, 4-7 or 8-11");
    }

    // The Q-channel data is constructed from the Q-mode (4 bits) and control bits (4 bits)
    // Q-mode is 0-3 and control is 4-7
    qChannelData[0] = controlNybble << 4 | modeNybble;

    // Get the frame metadata
    SectionType frameType = sectionMetadata.sectionType();
    SectionTime fTime = sectionMetadata.sectionTime();
    SectionTime apTime = sectionMetadata.absoluteSectionTime();
    quint8 trackNumber = sectionMetadata.trackNumber();

    // Sanity check the track number and frame type
    //
    // If the track number is 0, then this is a lead-in frame
    // If the track number is 0xAA, then this is a lead-out frame
    // If the track number is 1-99, then this is a user data frame
    if (trackNumber == 0 && frameType.type() != SectionType::LeadIn) {
        qFatal("Subcode::toData(): Track number 0 is only valid for lead-in frames");
    } else if (trackNumber == 0xAA && frameType.type() != SectionType::LeadOut) {
        qFatal("Subcode::toData(): Track number 0xAA is only valid for lead-out frames");
    } else if (trackNumber > 99) {
        qFatal("Subcode::toData(): Track number %d is out of range", trackNumber);
    }

    // Set the Q-channel data
    if (frameType.type() == SectionType::LeadIn) {
        quint16 tno = 0x00;
        quint16 pointer = 0x00;
        quint8 zero = 0;

        qChannelData[1] = tno;
        qChannelData[2] = pointer;
        qChannelData[3] = fTime.toBcd()[0];
        qChannelData[4] = fTime.toBcd()[1];
        qChannelData[5] = fTime.toBcd()[2];
        qChannelData[6] = zero;
        qChannelData[7] = apTime.toBcd()[0];
        qChannelData[8] = apTime.toBcd()[1];
        qChannelData[9] = apTime.toBcd()[2];
        }

        if (frameType.type() == SectionType::UserData) {
        quint8 tno = intToBcd2(trackNumber);
        quint8 index = 01; // Not correct?
        quint8 zero = 0;

        qChannelData[1] = tno;
        qChannelData[2] = index;
        qChannelData[3] = fTime.toBcd()[0];
        qChannelData[4] = fTime.toBcd()[1];
        qChannelData[5] = fTime.toBcd()[2];
        qChannelData[6] = zero;
        qChannelData[7] = apTime.toBcd()[0];
        qChannelData[8] = apTime.toBcd()[1];
        qChannelData[9] = apTime.toBcd()[2];
        }

        if (frameType.type() == SectionType::LeadOut) {
        quint16 tno = 0xAA; // Hexidecimal AA for lead-out
        quint16 index = 01; // Must be 01 for lead-out
        quint8 zero = 0;

        qChannelData[1] = tno;
        qChannelData[2] = index;
        qChannelData[3] = fTime.toBcd()[0];
        qChannelData[4] = fTime.toBcd()[1];
        qChannelData[5] = fTime.toBcd()[2];
        qChannelData[6] = zero;
        qChannelData[7] = apTime.toBcd()[0];
        qChannelData[8] = apTime.toBcd()[1];
        qChannelData[9] = apTime.toBcd()[2];
    }

    // Set the CRC
    setQChannelCrc(qChannelData); // Sets data[10] and data[11]

    // Now we need to convert the p-channel and q-channel data into a 98 byte array
    QByteArray data;
    data.resize(98);
    data[0] = 0x00; // Sync0
    data[1] = 0x00; // Sync1

    for (int index = 2; index < 98; ++index) {
        quint8 m_subcodeByte = 0x00;
        if (getBit(pChannelData, index - 2))
            m_subcodeByte |= 0x80;
        if (getBit(qChannelData, index - 2))
            m_subcodeByte |= 0x40;
        data[index] = m_subcodeByte;
    }

    return data;
}

// Set a bit in a byte array
void Subcode::setBit(QByteArray &data, quint8 bitPosition, bool value)
{
    // Check to ensure the bit position is valid
    if (bitPosition >= data.size() * 8) {
        qFatal("Subcode::setBit(): Bit position %d is out of range for data size %d", bitPosition,
               data.size());
    }

    // We need to convert this to a byte number and bit number within that byte
    quint8 byteNumber = bitPosition / 8;
    quint8 bitNumber = 7 - (bitPosition % 8);

    // Set the bit
    if (value) {
        data[byteNumber] = static_cast<uchar>(data[byteNumber] | (1 << bitNumber)); // Set bit
    } else {
        data[byteNumber] = static_cast<uchar>(data[byteNumber] & ~(1 << bitNumber)); // Clear bit
    }
}

// Get a bit from a byte array
bool Subcode::getBit(const QByteArray &data, quint8 bitPosition)
{
    // Check to ensure we don't overflow the data array
    if (bitPosition >= data.size() * 8) {
        qFatal("Subcode::getBit(): Bit position %d is out of range for data size %d", bitPosition,
               data.size());
    }

    // We need to convert this to a byte number and bit number within that byte
    quint8 byteNumber = bitPosition / 8;
    quint8 bitNumber = 7 - (bitPosition % 8);

    // Get the bit
    return (data[byteNumber] & (1 << bitNumber)) != 0;
}

bool Subcode::isCrcValid(QByteArray qChannelData)
{
    // Get the CRC from the data
    quint16 dataCrc = getQChannelCrc(qChannelData);

    // Calculate the CRC
    quint16 calculatedCrc = calculateQChannelCrc16(qChannelData);

    // Check if the CRC is valid
    return dataCrc == calculatedCrc;
}

quint16 Subcode::getQChannelCrc(QByteArray qChannelData)
{
    // Get the CRC from the data
    return static_cast<quint16>(static_cast<uchar>(qChannelData[10]) << 8
                                 | static_cast<uchar>(qChannelData[11]));
}

void Subcode::setQChannelCrc(QByteArray &qChannelData)
{
    // Calculate the CRC
    quint16 calculatedCrc = calculateQChannelCrc16(qChannelData);

    // Set the CRC in the data
    qChannelData[10] = static_cast<quint8>(calculatedCrc >> 8);
    qChannelData[11] = static_cast<quint8>(calculatedCrc & 0xFF);
}

// Generate a 16-bit CRC for the subcode data
// Adapted from http://mdfs.net/Info/Comp/Comms/CRC16.htm
quint16 Subcode::calculateQChannelCrc16(const QByteArray &qChannelData)
{
    qsizetype i;
    quint32 crc = 0;

    // Remove the last 2 bytes
    QByteArray data = qChannelData.left(qChannelData.size() - 2);

    for (int pos = 0; pos < data.size(); ++pos) {
        crc = crc ^ static_cast<quint32>(static_cast<uchar>(data[pos]) << 8);
        for (i = 0; i < 8; ++i) {
            crc = crc << 1;
            if (crc & 0x10000)
                crc = (crc ^ 0x1021) & 0xFFFF;
        }
    }

    // Invert the CRC
    crc = ~crc & 0xFFFF;

    return static_cast<quint16>(crc);
}

// Because of the way Q-channel data is spread over many frames, the most
// likely cause of a CRC error is a single bit error in the data. We can
// attempt to repair the data by flipping each bit in turn and checking
// the CRC.
//
// Perhaps there is some more effective way to repair the data, but this
// will do for now.
bool Subcode::repairData(QByteArray &qChannelData)
{
    QByteArray dataCopy = qChannelData;

    // 96-16 = Don't repair CRC bits
    for (int i = 0; i < 96 - 16; ++i) {
        dataCopy = qChannelData;
        dataCopy[i / 8] = static_cast<uchar>(dataCopy[i / 8] ^ (1 << (7 - (i % 8))));

        if (isCrcValid(dataCopy)) {
            qChannelData = dataCopy;
            return true;
        }
    }

    return false;
}

// Convert integer to BCD (Binary Coded Decimal)
// Output is always 2 nybbles (00-99)
quint8 Subcode::intToBcd2(quint8 value)
{
    if (value > 99) {
        qFatal("Subcode::intToBcd2(): Value must be in the range 0 to 99. Got %d", value);
    }

    quint16 bcd = 0;
    quint16 factor = 1;

    while (value > 0) {
        bcd += (value % 10) * factor;
        value /= 10;
        factor *= 16;
    }

    // Ensure the result is always 2 bytes (00-99)
    return bcd & 0xFF;
}

// Convert BCD (Binary Coded Decimal) to integer
quint8 Subcode::bcd2ToInt(quint8 bcd)
{
    quint16 value = 0;
    quint16 factor = 1;

    // Check for the lead out track exception of 0xAA
    // (See ECMA-130 22.3.3.1)
    if (bcd == 0xAA) {
        return 0xAA;
    }

    while (bcd > 0) {
        value += (bcd & 0x0F) * factor;
        bcd >>= 4;
        factor *= 10;
    }

    return value;
}