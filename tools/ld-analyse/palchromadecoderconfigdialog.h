/************************************************************************

    palchromadecoderconfigdialog.h

    ld-analyse - TBC output analysis
    Copyright (C) 2019 Simon Inns

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

#ifndef PALCHROMADECODERCONFIGDIALOG_H
#define PALCHROMADECODERCONFIGDIALOG_H

#include <QDialog>

#include "palcolour.h"

namespace Ui {
class PalChromaDecoderConfigDialog;
}

class PalChromaDecoderConfigDialog : public QDialog
{
    Q_OBJECT

public:
    explicit PalChromaDecoderConfigDialog(QWidget *parent = nullptr);
    ~PalChromaDecoderConfigDialog();

    void setConfiguration(const PalColour::Configuration &_palChromaDecoderConfig);
    const PalColour::Configuration &getConfiguration();

signals:
    void palChromaDecoderConfigChanged();

private slots:
    void on_chromaGainHorizontalSlider_valueChanged(int value);
    void on_twoDeeTransformCheckBox_clicked();
    void on_thresholdModeCheckBox_clicked();
    void on_thresholdHorizontalSlider_valueChanged(int value);
    void on_showFFTsCheckBox_clicked();
    void on_simplePALCheckBox_clicked();

private:
    Ui::PalChromaDecoderConfigDialog *ui;
    PalColour::Configuration palChromaDecoderConfig;

    void updateDialog();
};

#endif // PALCHROMADECODERCONFIGDIALOG_H
