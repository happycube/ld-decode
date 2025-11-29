/******************************************************************************
 * vbidialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2018-2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef VBIDIALOG_H
#define VBIDIALOG_H

#include <QDialog>

#include "lddecodemetadata.h"
#include "vbidecoder.h"
#include "videoiddecoder.h"

namespace Ui {
class VbiDialog;
}

class VbiDialog : public QDialog
{
    Q_OBJECT

public:
    explicit VbiDialog(QWidget *parent = nullptr);
    ~VbiDialog();

    void updateVbi(VbiDecoder::Vbi vbi, bool isVbiValid);
    void updateVideoId(VideoIdDecoder::VideoId videoid, bool isVideoIdValid);

private:
    Ui::VbiDialog *ui;

    VbiDecoder vbiDecoder;
    VideoIdDecoder videoIdDecoder;
};

#endif // VBIDIALOG_H
