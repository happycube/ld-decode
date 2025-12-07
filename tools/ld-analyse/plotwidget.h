/******************************************************************************
 * plotwidget.h
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#ifndef PLOTWIDGET_H
#define PLOTWIDGET_H

#include <QWidget>
#include <QGraphicsView>
#include <QGraphicsScene>
#include <QGraphicsItem>
#include <QGraphicsLineItem>
#include <QGraphicsTextItem>
#include <QGraphicsPathItem>
#include <QPainter>
#include <QPainterPath>
#include <QWheelEvent>
#include <QMouseEvent>
#include <QRubberBand>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QColor>
#include <QPen>
#include <QBrush>
#include <QFont>
#include <QFontMetrics>
#include <QVector>
#include <QPointF>

class PlotGrid;
class PlotSeries;
class PlotMarker;
class PlotLegend;
class PlotAxisLabels;

class PlotWidget : public QWidget
{
    Q_OBJECT

public:
    explicit PlotWidget(QWidget *parent = nullptr);
    ~PlotWidget();

    // Axis management
    void setAxisTitle(Qt::Orientation orientation, const QString &title);
    void setAxisRange(Qt::Orientation orientation, double min, double max);
    void setAxisAutoScale(Qt::Orientation orientation, bool enable);
    void setYAxisIntegerLabels(bool integerOnly);
    
    // Grid
    void setGridEnabled(bool enabled);
    void setGridPen(const QPen &pen);
    
    // Series
    PlotSeries* addSeries(const QString &title = QString());
    void removeSeries(PlotSeries *series);
    void clearSeries();
    
    // Markers
    PlotMarker* addMarker();
    void removeMarker(PlotMarker *marker);
    void clearMarkers();
    
    // Legend
    void setLegendEnabled(bool enabled);
    
    // Zooming and panning
    void setZoomEnabled(bool enabled);
    void setPanEnabled(bool enabled);
    void resetZoom();
    
    // Canvas
    void setCanvasBackground(const QColor &color);
    
    // Theme
    void updateTheme();
    static bool isDarkTheme();
    
    // Replot
    void replot();

signals:
    void plotAreaChanged(const QRectF &rect);
    void seriesClicked(PlotSeries *series, const QPointF &point);

protected:
    void resizeEvent(QResizeEvent *event) override;

private slots:
    void onSceneSelectionChanged();

private:
    QGraphicsView *m_view;
    QGraphicsScene *m_scene;
    QVBoxLayout *m_mainLayout;
    
    // Plot area
    QRectF m_plotRect;
    QRectF m_dataRect;
    
    // Axes
    QString m_xAxisTitle;
    QString m_yAxisTitle;
    double m_xMin, m_xMax;
    double m_yMin, m_yMax;
    bool m_xAutoScale;
    bool m_yAutoScale;
    bool m_yIntegerLabels;
    bool m_isDarkTheme;
    
    // Components
    PlotGrid *m_grid;
    PlotLegend *m_legend;
    PlotAxisLabels *m_axisLabels;
    QList<PlotSeries*> m_series;
    QList<PlotMarker*> m_markers;
    
    // Settings
    bool m_gridEnabled;
    bool m_legendEnabled;
    bool m_zoomEnabled;
    bool m_panEnabled;
    QColor m_canvasBackground;
    
public:
    // Coordinate mapping methods (needed by plot items)
    QPointF mapToData(const QPointF &scenePos) const;
    QPointF mapFromData(const QPointF &dataPos) const;

private:
    // Helper methods
    void setupView();
    void updatePlotArea();
    void updateAxisLabels();
    void calculateDataRange();
};

// Plot series class for drawing data series
class PlotSeries : public QGraphicsPathItem
{
public:
    enum PlotStyle {
        Lines,  // Connect points with lines (default)
        Bars    // Draw vertical bars from x-axis to each point
    };
    
    explicit PlotSeries(PlotWidget *parent = nullptr);
    
    void setTitle(const QString &title);
    QString title() const { return m_title; }
    
    void setPen(const QPen &pen);
    void setBrush(const QBrush &brush);
    
    void setStyle(PlotStyle style);
    PlotStyle style() const { return m_style; }
    
    void setData(const QVector<QPointF> &data);
    void setData(const QVector<double> &xData, const QVector<double> &yData);
    
    void setVisible(bool visible);
    
    QVector<QPointF> data() const { return m_data; }
    
    void updatePath(const QRectF &plotRect, const QRectF &dataRect);

private:
    QString m_title;
    QVector<QPointF> m_data;
    PlotStyle m_style;
    PlotWidget *m_plotWidget;
};

// Plot grid class for drawing grid lines
class PlotGrid : public QGraphicsItem
{
public:
    explicit PlotGrid(PlotWidget *parent = nullptr);
    
    void setPen(const QPen &pen);
    void setEnabled(bool enabled);
    
    QRectF boundingRect() const override;
    void paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget) override;
    
    void updateGrid(const QRectF &plotRect, const QRectF &dataRect, bool isDarkTheme = false);

private:
    QPen m_pen;
    bool m_enabled;
    bool m_isDarkTheme;
    QRectF m_plotRect;
    QRectF m_dataRect;
    PlotWidget *m_plotWidget;
};

// Plot marker class for drawing markers
class PlotMarker : public QGraphicsItem
{
public:
    enum MarkerStyle {
        VLine,
        HLine,
        Cross
    };
    
    explicit PlotMarker(PlotWidget *parent = nullptr);
    
    void setStyle(MarkerStyle style);
    void setPen(const QPen &pen);
    void setPosition(const QPointF &pos);
    void setLabel(const QString &label);
    
    QRectF boundingRect() const override;
    void paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget) override;
    
    void updateMarker(const QRectF &plotRect, const QRectF &dataRect);

private:
    MarkerStyle m_style;
    QPen m_pen;
    QPointF m_dataPos;
    QString m_label;
    QRectF m_plotRect;
    QRectF m_dataRect;
    PlotWidget *m_plotWidget;
};

// Plot legend class
class PlotLegend : public QGraphicsItem
{
public:
    explicit PlotLegend(PlotWidget *parent = nullptr);
    
    void setEnabled(bool enabled);
    void updateLegend(const QList<PlotSeries*> &series, const QRectF &plotRect);
    
    QRectF boundingRect() const override;
    void paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget) override;

private:
    bool m_enabled;
    QList<PlotSeries*> m_series;
    QRectF m_boundingRect;
    PlotWidget *m_plotWidget;
};

// Plot axis labels class
class PlotAxisLabels : public QGraphicsItem
{
public:
    explicit PlotAxisLabels(PlotWidget *parent = nullptr);
    
    void updateLabels(const QRectF &plotRect, const QRectF &dataRect, 
                     const QString &xTitle, const QString &yTitle,
                     double xMin, double xMax, double yMin, double yMax,
                     bool yIntegerLabels = false, bool isDarkTheme = false);
    
    QRectF boundingRect() const override;
    void paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget) override;

private:
    QRectF m_plotRect;
    QRectF m_dataRect;
    QString m_xTitle;
    QString m_yTitle;
    bool m_yIntegerLabels;
    bool m_isDarkTheme;
    double m_xMin, m_xMax, m_yMin, m_yMax;
    PlotWidget *m_plotWidget;
};

#endif // PLOTWIDGET_H