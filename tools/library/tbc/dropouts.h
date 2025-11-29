/******************************************************************************
 * dropouts.h
 * ld-decode-tools TBC library
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef DROPOUTS_H
#define DROPOUTS_H

#include <QDebug>
#include <QtGlobal>
#include <QMetaType>

class SqliteReader;
class SqliteWriter;

class DropOuts
{
public:
    DropOuts() = default;
    DropOuts(int reserve);
    ~DropOuts() = default;
    DropOuts(const DropOuts &) = default;

    DropOuts(const QVector<qint32> &startx, const QVector<qint32> &endx, const QVector<qint32> &fieldLine);
    DropOuts &operator=(const DropOuts &);

    void append(const qint32 startx, const qint32 endx, const qint32 fieldLine);
    void reserve(int size);
    void resize(qint32 size);
    void clear();
    void concatenate(const bool verbose=true);

    // Return the number of dropouts
    qint32 size() const {
        return m_startx.size();
    }

    // Return true if there are no dropouts
    bool empty() const {
        return m_startx.empty();
    }

    // Get position of a dropout
    qint32 startx(qint32 index) const {
        return m_startx[index];
    }
    qint32 endx(qint32 index) const {
        return m_endx[index];
    }
    qint32 fieldLine(qint32 index) const {
        return m_fieldLine[index];
    }

    void read(SqliteReader &reader, int captureId, int fieldId);
    void write(SqliteWriter &writer, int captureId, int fieldId) const;

private:
    QVector<qint32> m_startx;
    QVector<qint32> m_endx;
    QVector<qint32> m_fieldLine;
};

#endif // DROPOUTS_H
