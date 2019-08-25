/************************************************************************

    transformpal.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

    Reusing code from pyctools-pal, which is:
    Copyright (C) 2014 Jim Easterbrook

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#include "transformpal.h"

TransformPal::TransformPal()
    : configurationSet(false)
{
}

TransformPal::~TransformPal()
{
}

void TransformPal::updateConfiguration(const LdDecodeMetaData::VideoParameters &_videoParameters,
                                       qint32 _firstActiveLine, qint32 _lastActiveLine,
                                       TransformPal::TransformMode _mode, double _threshold)
{
    videoParameters = _videoParameters;
    firstActiveLine = _firstActiveLine;
    lastActiveLine = _lastActiveLine;
    mode = _mode;
    threshold = _threshold;

    configurationSet = true;
}
