/************************************************************************

    logging.h

    ld-decode-tools TBC library
    Copyright (C) 2018-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
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

#ifndef TBC_LOGGING_H
#define TBC_LOGGING_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QString>
#include <QCommandLineParser>

#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

// Prototypes
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg);
void setDebug(bool state);
void setQuiet(bool state);
void setBinaryMode(void);
void openDebugFile(QString filename);
void closeDebugFile(void);
void addStandardDebugOptions(QCommandLineParser &parser);
void processStandardDebugOptions(QCommandLineParser &parser);
bool getDebugState();

// Lightweight application-level debug logger (not suppressed in release builds)
void tbcDebug(const QString &msg);

// Stream-style debug helper to ease migration from tbcDebugStream()
class TbcDebugStream
{
public:
    TbcDebugStream();
    ~TbcDebugStream();

    template<typename T>
    TbcDebugStream &operator<<(const T &value)
    {
        if (!enabled) return *this;
        debug << value;
        return *this;
    }

    // Match tbcDebugStream().nospace() semantics
    TbcDebugStream &nospace();
    // noquote is a no-op for our QTextStream-based logger
    TbcDebugStream &noquote();

private:
    QString buffer;
    bool enabled;
    QDebug debug;
};

TbcDebugStream tbcDebugStream();

// No aliasing of qDebug; use tbcDebugStream() explicitly in code for clarity

// Helper to stream multiple arguments into tbcDebug without qDebug
template<typename T>
inline void tbcDebugAppend(QTextStream &stream, const T &value)
{
    stream << value;
}

template<typename T, typename... Rest>
inline void tbcDebugAppend(QTextStream &stream, const T &value, const Rest&... rest)
{
    stream << value;
    tbcDebugAppend(stream, rest...);
}

template<typename... Args>
inline void tbcDebug(const Args&... args)
{
    QString message;
    QTextStream stream(&message);
    tbcDebugAppend(stream, args...);
    tbcDebug(message);
}

#endif // TBC_LOGGING_H
