/******************************************************************************
 * metadataconverter.cpp
 * ld-export-decode-metadata - metadata export tool for ld-decode
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "metadataconverter.h"
#include <QDebug>
#include <QFileInfo>
#include <QDir>

MetadataConverter::MetadataConverter(const QString &inputSqliteFilename, const QString &outputJsonFilename)
    : m_inputSqliteFilename(inputSqliteFilename), m_outputJsonFilename(outputJsonFilename)
{

}

MetadataConverter::~MetadataConverter()
{

}

bool MetadataConverter::process()
{
    LdDecodeMetaData ldDecodeMetaData;
    ExportMetaData exportMetaData;

    if (!ldDecodeMetaData.read(m_inputSqliteFilename)) {
		qCritical() << "Unable to open TBC metadata file - cannot continue";
		return false;
	}

	qInfo() << "Successfully loaded metadata";

	ExportMetaData::VideoParameters out_VideoParameters;

	if (!ExportMetaData::parseVideoSystemName(ldDecodeMetaData.getVideoSystemDescription(), out_VideoParameters.system)) {
		qCritical() << "Unsupported video system - cannot continue";
		return false;
	}

	convertVideoParamters(ldDecodeMetaData.getVideoParameters(), out_VideoParameters);
	exportMetaData.setVideoParameters(out_VideoParameters);

	try {
		ExportMetaData::PcmAudioParameters out_PcmAudioParameters;
		convertPcmAudioParamters(ldDecodeMetaData.getPcmAudioParameters(), out_PcmAudioParameters);
		exportMetaData.setPcmAudioParameters(out_PcmAudioParameters);
	} catch (...) {
		qInfo() << "No valid PcmAudioParameters, will not export audio information.";
	}

	for (qint32 fieldNum = 1; fieldNum <= ldDecodeMetaData.getNumberOfFields(); fieldNum++) {
		ExportMetaData::Field out_field;
		convertField(ldDecodeMetaData.getField(fieldNum), out_field);
		exportMetaData.appendField(out_field);
	}

    if (!exportMetaData.write(m_outputJsonFilename)) {
		qCritical() << "Unable to save export metadata file";
		return false;
	}

	qInfo() << "Successfully saved export metadata";
    
    return true;
}

void MetadataConverter::convertVideoParamters(const LdDecodeMetaData::VideoParameters &in_VideoParameters,
                                              ExportMetaData::VideoParameters &out_VideoParameters)
{
	out_VideoParameters.isSubcarrierLocked = in_VideoParameters.isSubcarrierLocked;
	out_VideoParameters.isWidescreen = in_VideoParameters.isWidescreen;
	out_VideoParameters.colourBurstStart = in_VideoParameters.colourBurstStart;
	out_VideoParameters.colourBurstEnd = in_VideoParameters.colourBurstEnd;
	out_VideoParameters.activeVideoStart = in_VideoParameters.activeVideoStart;
	out_VideoParameters.activeVideoEnd = in_VideoParameters.activeVideoEnd;
	out_VideoParameters.white16bIre = in_VideoParameters.white16bIre;
	out_VideoParameters.black16bIre = in_VideoParameters.black16bIre;
	out_VideoParameters.fieldWidth = in_VideoParameters.fieldWidth;
	out_VideoParameters.fieldHeight = in_VideoParameters.fieldHeight;
	out_VideoParameters.sampleRate = in_VideoParameters.sampleRate;
	out_VideoParameters.isMapped = in_VideoParameters.isMapped;
	out_VideoParameters.tapeFormat = in_VideoParameters.tapeFormat;
	out_VideoParameters.gitBranch = in_VideoParameters.gitBranch;
	out_VideoParameters.gitCommit = in_VideoParameters.gitCommit;
}

void MetadataConverter::convertPcmAudioParamters(const LdDecodeMetaData::PcmAudioParameters &in_PcmAudioParameters,
                                                 ExportMetaData::PcmAudioParameters &out_PcmAudioParameters)
{
	out_PcmAudioParameters.sampleRate = in_PcmAudioParameters.sampleRate;
	out_PcmAudioParameters.isLittleEndian = in_PcmAudioParameters.isLittleEndian;
	out_PcmAudioParameters.isSigned = in_PcmAudioParameters.isSigned;
	out_PcmAudioParameters.bits = in_PcmAudioParameters.bits;
	out_PcmAudioParameters.isValid = true;
}

void MetadataConverter::convertField(const LdDecodeMetaData::Field &in_field,
                                     ExportMetaData::Field &out_field)
{
	out_field.seqNo = in_field.seqNo;
	out_field.isFirstField = in_field.isFirstField;
	out_field.syncConf = in_field.syncConf;
	out_field.medianBurstIRE = in_field.medianBurstIRE;
	out_field.fieldPhaseID = in_field.fieldPhaseID;
	out_field.audioSamples = in_field.audioSamples;
	out_field.pad = in_field.pad;
	out_field.diskLoc = in_field.diskLoc;
	out_field.fileLoc = in_field.fileLoc;
	out_field.decodeFaults = in_field.decodeFaults;
	out_field.efmTValues = in_field.efmTValues;
	out_field.vitsMetrics.inUse = in_field.vitsMetrics.inUse;
	out_field.vitsMetrics.wSNR = in_field.vitsMetrics.wSNR;
	out_field.vitsMetrics.bPSNR = in_field.vitsMetrics.bPSNR;
	out_field.vbi.inUse = in_field.vbi.inUse;
	if (out_field.vbi.inUse)
		std::copy(in_field.vbi.vbiData.begin(), in_field.vbi.vbiData.end(), out_field.vbi.vbiData.begin());
	out_field.ntsc.inUse = in_field.ntsc.inUse;
	out_field.ntsc.isFmCodeDataValid = in_field.ntsc.isFmCodeDataValid;
	out_field.ntsc.fmCodeData = in_field.ntsc.fmCodeData;
	out_field.ntsc.fieldFlag = in_field.ntsc.fieldFlag;
	out_field.ntsc.isVideoIdDataValid = out_field.ntsc.isVideoIdDataValid;
	out_field.ntsc.videoIdData = out_field.ntsc.videoIdData;
	out_field.ntsc.whiteFlag = out_field.ntsc.whiteFlag;
	out_field.vitc.inUse = in_field.vitc.inUse;
	if (out_field.vitc.inUse)
		std::copy(in_field.vitc.vitcData.begin(), in_field.vitc.vitcData.end(), out_field.vitc.vitcData.begin());
	out_field.closedCaption.inUse = in_field.closedCaption.inUse;
	out_field.closedCaption.data0 = in_field.closedCaption.data0;
	out_field.closedCaption.data1 = in_field.closedCaption.data1;
	for (int i=0; i<in_field.dropOuts.size(); i++) {
		out_field.dropOuts.append(in_field.dropOuts.startx(i), in_field.dropOuts.endx(i), in_field.dropOuts.fieldLine(i));
	}
}
