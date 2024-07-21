/************************************************************************

    stacker.cpp

    ld-disc-stacker - Disc stacking for ld-decode
    Copyright (C) 2020-2022 Simon Inns

    This file is part of ld-decode-tools.

    ld-disc-stacker is free software: you can redistribute it and/or
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

#include "stacker.h"
#include "stackingpool.h"

Stacker::Stacker(QAtomicInt& _abort, StackingPool& _stackingPool, QObject *parent)
    : QThread(parent), abort(_abort), stackingPool(_stackingPool)
{
}

void Stacker::run()
{
    // Variables for getInputFrame
    qint32 frameNumber;
    QVector<qint32> firstFieldSeqNo;
    QVector<qint32> secondFieldSeqNo;
    QVector<SourceVideo::Data> firstSourceField;
    QVector<SourceVideo::Data> secondSourceField;
    QVector<LdDecodeMetaData::Field> firstFieldMetadata;
    QVector<LdDecodeMetaData::Field> secondFieldMetadata;
	qint32 mode;
	qint32 smartTreshold;
    bool reverse;
    bool noDiffDod;
    bool passThrough;
    QVector<qint32> availableSourcesForFrame;

    while(!abort) {
        // Get the next field to process from the input file
        if (!stackingPool.getInputFrame(frameNumber, firstFieldSeqNo, firstSourceField, firstFieldMetadata,
                                       secondFieldSeqNo, secondSourceField, secondFieldMetadata,
                                       videoParameters, mode, smartTreshold, reverse, noDiffDod, passThrough,
                                       availableSourcesForFrame)) {
            // No more input fields -- exit
            break;
        }

        // Initialise the output fields and process sources to output
        SourceVideo::Data outputFirstField(firstSourceField[0].size());
        SourceVideo::Data outputSecondField(secondSourceField[0].size());
        DropOuts outputFirstFieldDropOuts;
        DropOuts outputSecondFieldDropOuts;

        stackField(frameNumber, firstSourceField, videoParameters[0], firstFieldMetadata, availableSourcesForFrame, noDiffDod, passThrough, outputFirstField, outputFirstFieldDropOuts, mode, smartTreshold);
        stackField(frameNumber, secondSourceField, videoParameters[0], secondFieldMetadata, availableSourcesForFrame, noDiffDod, passThrough, outputSecondField, outputSecondFieldDropOuts, mode, smartTreshold);

        // Return the processed fields
        stackingPool.setOutputFrame(frameNumber, outputFirstField, outputSecondField,
                                    firstFieldSeqNo[0], secondFieldSeqNo[0],
                                    outputFirstFieldDropOuts, outputSecondFieldDropOuts);
    }
}

// Method to stack fields
void Stacker::stackField(qint32 frameNumber, QVector<SourceVideo::Data> inputFields,
                                      LdDecodeMetaData::VideoParameters videoParameters,
                                      QVector<LdDecodeMetaData::Field> fieldMetadata,
                                      QVector<qint32> availableSourcesForFrame,
                                      bool noDiffDod, bool passThrough,
                                      SourceVideo::Data &outputField,
                                      DropOuts &dropOuts,
                                      qint32 mode,
                                      qint32 smartTreshold)
{
    quint16 prevGoodValue = videoParameters.black16bIre;
    bool forceDropout = false;

    if (availableSourcesForFrame.size() > 0) {
        // Sources available - process field
        for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
            for (qint32 x = videoParameters.colourBurstStart; x < videoParameters.fieldWidth; x++) {
                // Get input values from the input sources (which are not marked as dropouts)
                QVector<quint16> inputValuesN;//Nort neighbor pixel
                QVector<quint16> inputValuesS;//South neighbor pixel
                QVector<quint16> inputValuesE;//East neighbor pixel
                QVector<quint16> inputValuesW;//West neighbor pixel
                QVector<quint16> inputValues;
                for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
                    // Include the source's pixel data if it's not marked as a dropout
                    if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y)) {
                        // Pixel is valid
                        inputValues.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x]);
                    }
                }
				if(mode == 2 && !(availableSourcesForFrame.size() % 2))//get surounding pixels if we have even number of sample 
				{
					for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
						// Include the source's pixel data if it's not marked as a dropout
						if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y) && (y - 1) > 0) {
							// Pixel is valid
							inputValuesN.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * (y - 1)) + x]);
						}
						if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y) && (y + 1) < videoParameters.fieldHeight) {
							// Pixel is valid
							inputValuesS.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * (y + 1)) + x]);
						}
						if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y) && (x + 1) < videoParameters.fieldWidth) {
							// Pixel is valid
							inputValuesE.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x + 1]);
						}
						if (!isDropout(fieldMetadata[availableSourcesForFrame[i]].dropOuts, x, y) && (x - 1) > 0) {
							// Pixel is valid
							inputValuesW.append(inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x - 1]);
						}
					}
				}

                // If passThrough is set, the output is always marked as a dropout if all input values are dropouts
                // (regardless of the diffDOD process result).
                forceDropout = false;
                if ((availableSourcesForFrame.size() > 0) && (passThrough)) {
                    if (inputValues.size() == 0) {
                        forceDropout = true;
                        qInfo().nospace() << "Frame #" << frameNumber << ": All sources for field location (" << x << ", " << y << ") are marked as dropout, passing through";
                    }
                }

                // If all possible input values are dropouts (and noDiffDod is false) and there are more than 3 input sources...
                // Take the available values (marked as dropouts) and perform a diffDOD to try and determine if the dropout markings
                // are false positives.
                if ((inputValues.size() == 0) && (availableSourcesForFrame.size() >= 3) && (noDiffDod == false)) {
                    // Clear the current input values and recreate the list including marked dropouts
                    inputValues.clear();
                    for (qint32 i = 0; i < availableSourcesForFrame.size(); i++) {
                        quint16 pixelValue = inputFields[availableSourcesForFrame[i]][(videoParameters.fieldWidth * y) + x];
                        if (pixelValue > 0) inputValues.append(pixelValue);
                    }

                    // Perform differential dropout detection to recover ld-decode false positive pixels
                    inputValues = diffDod(inputValues, videoParameters, x);

                    if (inputValues.size() > 0) {
                        qInfo().nospace() << "Frame #" << frameNumber << ": DiffDOD recovered " << inputValues.size() <<
                                             " values: " << inputValues << " for field location (" << x << ", " << y << ")";
                    } else {
                        qInfo().nospace() << "Frame #" << frameNumber << ": DiffDOD failed, no values recovered for field location (" << x << ", " << y << ")";
                    }
					if(mode == 2 && !(availableSourcesForFrame.size() % 2))
					{
						// Perform differential dropout detection to recover ld-decode false positive pixels
						inputValuesN = diffDod(inputValuesN, videoParameters, x);
						inputValuesS = diffDod(inputValuesS, videoParameters, x);
						if((x + 1) < videoParameters.fieldWidth)
						{
							inputValuesE = diffDod(inputValuesE, videoParameters, x + 1);
						}
						if((x - 1) > 0)
						{
							inputValuesW = diffDod(inputValuesW, videoParameters, x - 1);
						}
						
					}
                }

                // Stack with intelligence:
                // If there are 3 or more sources - median (with central average for non-odd source sets)
                // If there are 2 sources - average
                // If there is 1 source - output as is
                // If there are zero sources - mark as a dropout in the output file
                if (inputValues.size() == 0) {
                    // No values available - use the previous good value and mark as a dropout
                    outputField[(videoParameters.fieldWidth * y) + x] = prevGoodValue;
                    dropOuts.append(x, x, y + 1);
                } else if (inputValues.size() == 1) {
                    // 1 value available - just copy it to the output
                    outputField[(videoParameters.fieldWidth * y) + x] = inputValues[0];
                    prevGoodValue = outputField[(videoParameters.fieldWidth * y) + x];
                    if (forceDropout) dropOuts.append(x, x, y + 1);
                } else {
                    //2 or more values available - store the result in the output field
                    outputField[(videoParameters.fieldWidth * y) + x] = stackMode(inputValues, inputValuesN, inputValuesS, inputValuesE, inputValuesW, mode, smartTreshold);
                    prevGoodValue = outputField[(videoParameters.fieldWidth * y) + x];
                    if (forceDropout) dropOuts.append(x, x, y + 1);
                }
            }
        }

        // Concatenate the dropouts
        if (dropOuts.size() != 0) dropOuts.concatenate();
    } else {
        // No sources available for field - generate a dummy field at the black IRE level
        for (qint32 y = 0; y < videoParameters.fieldHeight; y++) {
            for (qint32 x = videoParameters.colourBurstStart; x < videoParameters.fieldWidth; x++) {
                outputField[(videoParameters.fieldWidth * y) + x] = videoParameters.black16bIre;
            }
        }
    }
}

// Method to stack a vector of quint16s using a selected mode
quint16 Stacker::stackMode(QVector<quint16> elements, QVector<quint16> elementsN, QVector<quint16> elementsS, QVector<quint16> elementsE, QVector<quint16> elementsW, qint32 mode, qint32 smartTreshold)
{
    qint32 noOfElements = elements.size();
	qint32 nbSelected = 0;
	quint32 result = 0;
	//qint32 median = 0;
	QVector<quint16> closestList;
	
	//neighbor pixel
	quint32 resultN = 0;
	quint32 resultS = 0;
	quint32 resultE = 0;
	quint32 resultW = 0;
	quint32 resultNeighbor = 0;
	
	qint32 nbNeighbor = 0;
	
	if(noOfElements < 3 && mode == 1)
	{
		mode = 0;
	}
	
	if(mode == 0)//mean mode
	{
		result = Stacker::mean(elements);
	}
	else if(mode == 1)//median mode
	{
		result = Stacker::median(elements);
	}
	else if(mode == 3)//neighbor mode
	{
		(noOfElements > 2)     ? result  = Stacker::median(elements)  : result  = Stacker::mean(elements);
		(elementsN.size() > 2) ? resultN = Stacker::median(elementsN) : resultN = Stacker::mean(elementsN);
		(elementsS.size() > 2) ? resultS = Stacker::median(elementsS) : resultS = Stacker::mean(elementsS);
		(elementsE.size() > 2) ? resultE = Stacker::median(elementsE) : resultE = Stacker::mean(elementsE);
		(elementsW.size() > 2) ? resultW = Stacker::median(elementsW) : resultW = Stacker::mean(elementsW);
		
		//check number of neighbor available and prepare for mean
		(resultN != -1) ? nbNeighbor++ : resultN = 0;
		(resultS != -1) ? nbNeighbor++ : resultS = 0;
		(resultE != -1) ? nbNeighbor++ : resultE = 0;
		(resultW != -1) ? nbNeighbor++ : resultW = 0;
		
		if(nbNeighbor > 0)
		{
			closestList.append(Stacker::closest(elements, resultN));
			closestList.append(Stacker::closest(elements, resultS));
			closestList.append(Stacker::closest(elements, resultE));
			closestList.append(Stacker::closest(elements, resultW));
			
			resultNeighbor = Stacker::closest(closestList, result);//get the closest value to the median/mean based on closest value to a neighbor
			result = (result + resultNeighbor) / 2;// get the mean between (median/mean) and the closest value to neighbor
		}
		return result;
	}
	else//smart mode
	{
		(noOfElements > 2)     ? result  = Stacker::median(elements)  : result  = Stacker::mean(elements);
		(elementsN.size() > 2) ? resultN = Stacker::median(elementsN) : resultN = Stacker::mean(elementsN);
		(elementsS.size() > 2) ? resultS = Stacker::median(elementsS) : resultS = Stacker::mean(elementsS);
		(elementsE.size() > 2) ? resultE = Stacker::median(elementsE) : resultE = Stacker::mean(elementsE);
		(elementsW.size() > 2) ? resultW = Stacker::median(elementsW) : resultW = Stacker::mean(elementsW);
		
		//check number of neighbor available and prepare for mean
		(resultN != -1) ? nbNeighbor++ : resultN = 0;
		(resultS != -1) ? nbNeighbor++ : resultS = 0;
		(resultE != -1) ? nbNeighbor++ : resultE = 0;
		(resultW != -1) ? nbNeighbor++ : resultW = 0;
		
		if(nbNeighbor > 0)
		{
			closestList.append(Stacker::closest(elements, resultN));
			closestList.append(Stacker::closest(elements, resultS));
			closestList.append(Stacker::closest(elements, resultE));
			closestList.append(Stacker::closest(elements, resultW));
			
			resultNeighbor = Stacker::closest(closestList, result);//get the closest value to the median/mean based on closest value to a neighbor
		}
		else
		{
			resultNeighbor = result;
		}
		
		if(noOfElements > 2)//using median + mean
		{
			result = 0;
			//count number of sample withing treshold distance to the median and sum
			for(int i=0; i < noOfElements;i++)
			{
				if((elements[i] < (resultNeighbor + smartTreshold)) && (elements[i] > (resultNeighbor - smartTreshold)))
				{
					nbSelected++;
					result += elements[i];
				}
			}
			//qInfo() << "selected " << nbSelected << "/" + noOfElements << " samples";
			//select median if all other source are out of the treshold range
			if(nbSelected == 0)
			{
				result = resultNeighbor;			
			}
			//mean averaging of selected sample
			else
			{
				result = (result / nbSelected);
			}
		}
		else//using surounding sample
		{
			result = (result + resultNeighbor) / 2;// get the mean between (median/mean) and the closest value to neighbor
		}
	}

    return static_cast<quint16>(result);
}

// Method to find the median of a vector of quint16s
quint16 Stacker::median(QVector<quint16> elements)
{
    qint32 noOfElements = elements.size();

    if (noOfElements % 2 == 0) {
        // Input set is even length

        // Applying nth_element on n/2th index
        std::nth_element(elements.begin(), elements.begin() + noOfElements / 2, elements.end());

        // Applying nth_element on (n-1)/2 th index
        std::nth_element(elements.begin(), elements.begin() + (noOfElements - 1) / 2, elements.end());

        // Find the average of value at index N/2 and (N-1)/2
        return static_cast<quint16>((elements[(noOfElements - 1) / 2] + elements[noOfElements / 2]) / 2.0);
    } else {
        // Input set is odd length

        // Applying nth_element on n/2
        std::nth_element(elements.begin(), elements.begin() + noOfElements / 2, elements.end());

        // Value at index (N/2)th is the median
        return static_cast<quint16>(elements[noOfElements / 2]);
    }
}

// Method to find the median of a vector of quint16s
qint32 Stacker::mean(QVector<quint16> elements)
{
	quint32 result = 0;
    qint32 noOfElements = elements.size();
	
	if(noOfElements > 1)
	{
		//compute mean of all values
		for(int i=0; i < noOfElements;i++)
		{
			if(noOfElements > 1)
			{
				result += elements[i];
			}
		}
		return (result / noOfElements);
	}
	else if(noOfElements == 1)
	{
		return elements[0];
	}
	else
	{
		return -1;
	}
	
}

// Method to find the closest value to a target
quint16 Stacker::closest(QVector<quint16> elements, qint32 target)
{
    qint32 noOfElements = elements.size();
	qint32 closest = elements[0];
	
	if(noOfElements > 1)
	{
		for(int i=1;i < noOfElements;i++)
		{
			if(abs(target - elements[i]) < abs(target - closest))
			{
				closest = elements[i];
			}
		}
	}
	
	return closest;
}

// Method returns true if specified pixel is a dropout
bool Stacker::isDropout(DropOuts dropOuts, qint32 fieldX, qint32 fieldY)
{
    for (qint32 i = 0; i < dropOuts.size(); i++) {
        if ((dropOuts.fieldLine(i) - 1) == fieldY) {
            if ((fieldX >= dropOuts.startx(i)) && (fieldX <= dropOuts.endx(i)))
                return true;
        }
    }

    return false;
}

// Use differential dropout detection to remove suspected dropout error
// values from inputValues to produce the set of output values.  This generally improves everything, but
// might cause an increase in errors for really noisy frames (where the DOs are in the same place in
// multiple sources).  Another possible disadvantage is that diffDOD might pass through master plate errors
// which, whilst not technically errors, may be undesirable.
QVector<quint16> Stacker::diffDod(QVector<quint16> inputValues, LdDecodeMetaData::VideoParameters videoParameters, qint32 xPos)
{
    QVector<quint16> outputValues;

    // Check that we have at least 3 input values
    if (inputValues.size() < 3) {
        qDebug() << "diffDOD: Only received" << inputValues.size() << "input values, exiting";
        return outputValues;
    }

    // Check that we are in the colour burst or visible line area
    if (xPos < videoParameters.colourBurstStart) {
        qDebug() << "diffDOD: Pixel not in colourburst or visible area";
        return outputValues;
    }

    // Get the median value of the input values
    double medianValue = static_cast<double>(median(inputValues));

    // Set the matching threshold to +-10% of the median value
    double threshold = 10; // %

    // Set the maximum and minimum values for valid inputs
    double maxValueD = medianValue + ((medianValue / 100.0) * threshold);
    double minValueD = medianValue - ((medianValue / 100.0) * threshold);
    if (minValueD < 0) minValueD = 0;
    if (maxValueD > 65535) maxValueD = 65535;
    quint16 minValue = minValueD;
    quint16 maxValue = maxValueD;

    // Copy valid input values to the output set
    for (qint32 i = 0; i < inputValues.size(); i++) {
        if ((inputValues[i] > minValue) && (inputValues[i] < maxValue)) {
            outputValues.append(inputValues[i]);
        }
    }

    // Show debug
    qDebug() << "diffDOD:  Input" << inputValues;
    if (outputValues.size() == 0) {
        qDebug().nospace() << "diffDOD: Empty output... Range was " << minValue << "-" << maxValue << " with a median of " << medianValue;
    } else {
        qDebug() << "diffDOD: Output" << outputValues;
    }

    return outputValues;
}
