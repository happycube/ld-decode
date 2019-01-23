#ifndef YIQBUFFER_H
#define YIQBUFFER_H

#include <QCoreApplication>
#include <QVector>

#include "yiqline.h"

class YiqBuffer
{
public:
    YiqBuffer();

    void clear(void);
    YiqLine& operator[] (const int index);
    QVector<qreal> yValues(void);

    QVector<YiqLine> yiqLine;
};

#endif // YIQBUFFER_H
