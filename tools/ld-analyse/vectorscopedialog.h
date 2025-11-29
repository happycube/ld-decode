/******************************************************************************
 * vectorscopedialog.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2022 Adam Sampson
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef VECTORSCOPEDIALOG_H
#define VECTORSCOPEDIALOG_H

#include <QAbstractButton>
#include <QGraphicsPixmapItem>
#include <QDialog>

#include "componentframe.h"
#include "lddecodemetadata.h"
#include "tbcsource.h"

namespace Ui {
class VectorscopeDialog;
}

class VectorscopeDialog : public QDialog
{
    Q_OBJECT

public:
    explicit VectorscopeDialog(QWidget *parent = nullptr);
    ~VectorscopeDialog();

    void showTraceImage(const ComponentFrame &componentFrame, const LdDecodeMetaData::VideoParameters &videoParameters,
                        const TbcSource::ViewMode& viewMode, const bool isFirstField);

signals:
    void scopeChanged();

private slots:
    void on_defocusCheckBox_clicked();
    void on_blendColorCheckBox_clicked();
    void on_graticuleButtonGroup_buttonClicked(QAbstractButton *button);
    void on_fieldSelectButtonGroup_buttonClicked(QAbstractButton *button);

private:
    Ui::VectorscopeDialog *ui;

    QImage getTraceImage(const ComponentFrame &componentFrame, const LdDecodeMetaData::VideoParameters &videoParameters);
};

#endif // VECTORSCOPEDIALOG_H
