/************************************************************************

    frameqlabel.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-analyse is free software: you can redistribute it and/or
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

#ifndef FRAMEQLABEL_H
#define FRAMEQLABEL_H

#include <QLabel>
#include <QPixmap>
#include <QResizeEvent>
#include <QDebug>

class FrameQLabel : public QLabel
{
public:
    Q_OBJECT

public:
    explicit FrameQLabel(QWidget *parent = nullptr);
    virtual qint32 heightForWidth(qint32 width) const;
    virtual QSize sizeHint() const;
    QPixmap scaledPixmap() const;

signals:
    void mouseOverQFrame(QMouseEvent *event);

public slots:
    void setPixmap (const QPixmap &);
    void resizeEvent(QResizeEvent *);
    void mouseMoveEvent(QMouseEvent *event);

private:
    QPixmap pix;
};

#endif // FRAMEQLABEL_H
