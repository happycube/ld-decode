#include "yiqbuffer.h"

YiqBuffer::YiqBuffer(void)
{
    yiqLine.resize(525);
}

void YiqBuffer::clear(void)
{
    yiqLine.clear();
    yiqLine.resize(525);
}

// Overload the [] operator to return an indexed value
YiqLine& YiqBuffer::operator[] (const int index)
{
    return yiqLine[index];
}

// Return a qreal vector of the Y values in the YIQ buffer
QVector<qreal> YiqBuffer::yValues(void)
{
    QVector<qreal> yReturn;

    for (qint32 line = 0; line < yiqLine.size(); line++) {
        for (qint32 pixel = 0; pixel < yiqLine[line].yiq.size(); pixel++) {
            yReturn.append(yiqLine[line].yiq[pixel].y);
        }
    }

    return yReturn;
}
