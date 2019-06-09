/************************************************************************

    sectorstometa.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "JsonWax/JsonWax.h"
#include "sectorstometa.h"

SectorsToMeta::SectorsToMeta()
{
    validSectors = 0;
    invalidSectors = 0;
}

// Method to open the metadata output file
bool SectorsToMeta::setOutputFile(QFile *outputFileHandle)
{
    // Open output file for writing
    this->outputFileHandle = outputFileHandle;

    // Here we just store the required filename
    // The file is created and filled on close
    jsonFilename = outputFileHandle->fileName();

    // Exit with success
    return true;
}

// Method to flush the metadata to the output file
void SectorsToMeta::flushMetadata(void)
{
    // Define the JSON object
    JsonWax json;

    // Write out the entries
    for (qint32 sectorNo = 0; sectorNo < metadata.size(); sectorNo++) {
        // Process entry
        json.setValue({"sector", sectorNo, "sectorNo"}, sectorNo);
        json.setValue({"sector", sectorNo, "mode"}, metadata[sectorNo].mode);
        json.setValue({"sector", sectorNo, "address"}, metadata[sectorNo].address.getTimeAsQString());
        json.setValue({"sector", sectorNo, "isCorrected"}, metadata[sectorNo].isCorrected);
    }

    // Write the JSON object to file
    qDebug() << "SectorsToMeta::closeOutputFile(): Writing JSON metadata file";
    if (!json.saveAs(jsonFilename, JsonWax::Readable)) {
        qCritical("Writing JSON file failed!");
        return;
    }
}

// Method to write status information to qInfo
void SectorsToMeta::reportStatus(void)
{
    qInfo() << "Sectors (data) to metadata processing:";
    qInfo() << "  Total number of sectors processed =" << validSectors + invalidSectors;
    qInfo() << "  Total number of valid sectors =" << validSectors;
    qInfo() << "  Total number of invalid sectors =" << invalidSectors;
}

// Method to process the decoded sections
void SectorsToMeta::process(QVector<Sector> sectors)
{
    // Did we get any sectors?
    if (sectors.size() != 0) {
        for (qint32 i = 0; i < sectors.size(); i++) {
            // Only record valid sectors (invalid sector my have a corrupt address)
            if (sectors[i].isValid()) {
                Metadatum tempMetadatum;
                tempMetadatum.address = sectors[i].getAddress();
                tempMetadatum.mode = sectors[i].getMode();
                tempMetadatum.isCorrected = sectors[i].isCorrected();
                metadata.append(tempMetadatum);
                validSectors++;
            } else {
                invalidSectors++;
            }
        }
    }
}
