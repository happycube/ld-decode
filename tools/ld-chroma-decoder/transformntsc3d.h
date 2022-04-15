/************************************************************************

    transformntsc3d.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019-2021 Adam Sampson

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

#ifndef TRANSFORMNTSC3D_H
#define TRANSFORMNTSC3D_H

#include <QVector>
#include <fftw3.h>

#include "componentframe.h"
#include "outputwriter.h"
#include "sourcefield.h"
#include "transformpal3d.h"

class TransformNtsc3D : public TransformPal3D {
public:
    void filterFields(const QVector<SourceField> &inputFields, qint32 startFieldIndex, qint32 endFieldIndex,
                      QVector<const double *> &outputFields) override;
  
protected:
    template <TransformMode MODE>
    void applyFilter();
    void overlayFFTFrame(qint32 positionX, qint32 positionY,
                         const QVector<SourceField> &inputFields, qint32 fieldIndex,
                         ComponentFrame &componentFrame) override;
};

#endif
