/******************************************************************************
 * plotwidget.cpp
 * ld-analyse - TBC output analysis GUI
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2025 Simon Inns
 *
 * This file is part of ld-decode-tools.
 ******************************************************************************/

#include "plotwidget.h"
#include <QDebug>
#include <QtMath>
#include <QApplication>

PlotWidget::PlotWidget(QWidget *parent)
    : QWidget(parent)
    , m_view(nullptr)
    , m_scene(nullptr)
    , m_mainLayout(nullptr)
    , m_plotRect(0, 0, 400, 300)
    , m_dataRect(0, 0, 100, 100)
    , m_xMin(0), m_xMax(100)
    , m_yMin(0), m_yMax(100)
    , m_xAutoScale(true)
    , m_yAutoScale(true)
    , m_yIntegerLabels(false)
    , m_isDarkTheme(false)
    , m_grid(nullptr)
    , m_legend(nullptr)
    , m_axisLabels(nullptr)
    , m_gridEnabled(true)
    , m_legendEnabled(false)
    , m_zoomEnabled(true)
    , m_panEnabled(true)
    , m_canvasBackground(Qt::white)
{
    setupView();
}

PlotWidget::~PlotWidget()
{
    clearSeries();
    clearMarkers();
}

void PlotWidget::setupView()
{
    m_mainLayout = new QVBoxLayout(this);
    m_mainLayout->setContentsMargins(0, 0, 0, 0);
    
    m_scene = new QGraphicsScene(this);
    m_view = new QGraphicsView(m_scene, this);
    
    m_view->setRenderHint(QPainter::Antialiasing, true);
    m_view->setDragMode(QGraphicsView::RubberBandDrag);
    m_view->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_view->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    
    m_mainLayout->addWidget(m_view);
    
    // Create grid
    m_grid = new PlotGrid(this);
    m_scene->addItem(m_grid);
    
    // Create legend
    m_legend = new PlotLegend(this);
    m_scene->addItem(m_legend);
    
    // Create axis labels
    m_axisLabels = new PlotAxisLabels(this);
    m_scene->addItem(m_axisLabels);
    
    // Detect and apply theme
    updateTheme();
    
    connect(m_scene, &QGraphicsScene::selectionChanged, this, &PlotWidget::onSceneSelectionChanged);
    
    updatePlotArea();
}

void PlotWidget::setAxisTitle(Qt::Orientation orientation, const QString &title)
{
    if (orientation == Qt::Horizontal) {
        m_xAxisTitle = title;
    } else {
        m_yAxisTitle = title;
    }
    replot();
}

void PlotWidget::setAxisRange(Qt::Orientation orientation, double min, double max)
{
    if (orientation == Qt::Horizontal) {
        m_xMin = min;
        m_xMax = max;
        m_xAutoScale = false;
    } else {
        m_yMin = min;
        m_yMax = max;
        m_yAutoScale = false;
    }
    replot();
}

void PlotWidget::setAxisAutoScale(Qt::Orientation orientation, bool enable)
{
    if (orientation == Qt::Horizontal) {
        m_xAutoScale = enable;
    } else {
        m_yAutoScale = enable;
    }
    if (enable) {
        calculateDataRange();
    }
    replot();
}

void PlotWidget::setYAxisIntegerLabels(bool integerOnly)
{
    m_yIntegerLabels = integerOnly;
    replot();
}

void PlotWidget::setGridEnabled(bool enabled)
{
    m_gridEnabled = enabled;
    if (m_grid) {
        m_grid->setEnabled(enabled);
    }
}

void PlotWidget::setGridPen(const QPen &pen)
{
    if (m_grid) {
        m_grid->setPen(pen);
    }
}

PlotSeries* PlotWidget::addSeries(const QString &title)
{
    PlotSeries *series = new PlotSeries(this);
    series->setTitle(title);
    m_series.append(series);
    m_scene->addItem(series);
    return series;
}

void PlotWidget::removeSeries(PlotSeries *series)
{
    if (series && m_series.contains(series)) {
        m_series.removeAll(series);
        m_scene->removeItem(series);
        delete series;
    }
}

void PlotWidget::clearSeries()
{
    for (PlotSeries *series : m_series) {
        m_scene->removeItem(series);
        delete series;
    }
    m_series.clear();
}

PlotMarker* PlotWidget::addMarker()
{
    PlotMarker *marker = new PlotMarker(this);
    m_markers.append(marker);
    m_scene->addItem(marker);
    return marker;
}

void PlotWidget::removeMarker(PlotMarker *marker)
{
    if (marker && m_markers.contains(marker)) {
        m_markers.removeAll(marker);
        m_scene->removeItem(marker);
        delete marker;
    }
}

void PlotWidget::clearMarkers()
{
    for (PlotMarker *marker : m_markers) {
        m_scene->removeItem(marker);
        delete marker;
    }
    m_markers.clear();
}

void PlotWidget::setLegendEnabled(bool enabled)
{
    m_legendEnabled = enabled;
    if (m_legend) {
        m_legend->setEnabled(enabled);
    }
}

void PlotWidget::setZoomEnabled(bool enabled)
{
    m_zoomEnabled = enabled;
    if (enabled) {
        m_view->setDragMode(QGraphicsView::RubberBandDrag);
    }
}

void PlotWidget::setPanEnabled(bool enabled)
{
    m_panEnabled = enabled;
}

void PlotWidget::resetZoom()
{
    m_view->fitInView(m_plotRect, Qt::KeepAspectRatio);
}

void PlotWidget::setCanvasBackground(const QColor &color)
{
    m_canvasBackground = color;
    m_scene->setBackgroundBrush(QBrush(color));
}

bool PlotWidget::isDarkTheme()
{
    // Check for command line overrides first
    QVariant themeProperty = QApplication::instance()->property("isDarkTheme");
    if (themeProperty.isValid()) {
        return themeProperty.toBool();
    }
    
    // Otherwise, use Qt's automatic palette detection (OS provides this)
    QPalette appPalette = QApplication::palette();
    QColor windowColor = appPalette.color(QPalette::Window);
    QColor textColor = appPalette.color(QPalette::WindowText);
    
    // Simple heuristic: if window is darker than text, we're in dark mode
    return windowColor.lightness() < textColor.lightness();
}

void PlotWidget::updateTheme()
{
    // Use the static utility function
    m_isDarkTheme = isDarkTheme();
    
    // Auto-set appropriate canvas background if not explicitly set
    if (m_canvasBackground == Qt::white || m_canvasBackground == QColor(42, 42, 42)) {
        QColor newBackground = m_isDarkTheme ? QColor(42, 42, 42) : Qt::white;
        setCanvasBackground(newBackground);
    }
    
    // Update all plot elements for the new theme
    replot();
}

void PlotWidget::replot()
{
    if (m_xAutoScale || m_yAutoScale) {
        calculateDataRange();
    }
    
    updatePlotArea();
    
    // Set scene rectangle to match our plot area with margins for labels
    QRectF sceneRect = QRectF(0, 0, m_view->width(), m_view->height());
    m_scene->setSceneRect(sceneRect);
    
    // Update all series
    for (PlotSeries *series : m_series) {
        series->updatePath(m_plotRect, m_dataRect);
    }
    
    // Update grid
    if (m_grid) {
        m_grid->updateGrid(m_plotRect, m_dataRect, m_isDarkTheme);
    }
    
    // Update markers
    for (PlotMarker *marker : m_markers) {
        marker->updateMarker(m_plotRect, m_dataRect);
    }
    
    // Update legend
    if (m_legend) {
        m_legend->updateLegend(m_series, m_plotRect);
    }
    
    // Update axis labels
    if (m_axisLabels) {
        m_axisLabels->updateLabels(m_plotRect, m_dataRect, m_xAxisTitle, m_yAxisTitle, 
                                  m_xMin, m_xMax, m_yMin, m_yMax, m_yIntegerLabels, m_isDarkTheme);
    }
    
    // Reset view transformation to 1:1 scale
    m_view->resetTransform();
    m_view->setSceneRect(sceneRect);
}

void PlotWidget::resizeEvent(QResizeEvent *event)
{
    QWidget::resizeEvent(event);
    updatePlotArea();
    replot();
}

void PlotWidget::onSceneSelectionChanged()
{
    // Handle selection changes if needed
}

void PlotWidget::updatePlotArea()
{
    QSize viewSize = m_view->size();
    const int leftMargin = 80;   // Space for Y-axis labels and title
    const int bottomMargin = 60; // Space for X-axis labels and title
    const int topMargin = 20;    // Small top margin
    const int rightMargin = 20;  // Small right margin
    
    m_plotRect = QRectF(leftMargin, topMargin, 
                       viewSize.width() - leftMargin - rightMargin, 
                       viewSize.height() - topMargin - bottomMargin);
    
    m_dataRect = QRectF(m_xMin, m_yMin, m_xMax - m_xMin, m_yMax - m_yMin);
}

void PlotWidget::calculateDataRange()
{
    if (m_series.isEmpty()) return;
    
    bool firstPoint = true;
    double xMin = 0, xMax = 0, yMin = 0, yMax = 0;
    
    for (PlotSeries *series : m_series) {
        const QVector<QPointF> &data = series->data();
        for (const QPointF &point : data) {
            if (firstPoint) {
                xMin = xMax = point.x();
                yMin = yMax = point.y();
                firstPoint = false;
            } else {
                xMin = qMin(xMin, point.x());
                xMax = qMax(xMax, point.x());
                yMin = qMin(yMin, point.y());
                yMax = qMax(yMax, point.y());
            }
        }
    }
    
    if (!firstPoint) {
        if (m_xAutoScale) {
            m_xMin = xMin;
            m_xMax = xMax;
        }
        if (m_yAutoScale) {
            m_yMin = yMin;
            m_yMax = yMax;
        }
    }
}

QPointF PlotWidget::mapToData(const QPointF &scenePos) const
{
    double x = m_xMin + (scenePos.x() - m_plotRect.left()) * (m_xMax - m_xMin) / m_plotRect.width();
    double y = m_yMax - (scenePos.y() - m_plotRect.top()) * (m_yMax - m_yMin) / m_plotRect.height();
    return QPointF(x, y);
}

QPointF PlotWidget::mapFromData(const QPointF &dataPos) const
{
    double x = m_plotRect.left() + (dataPos.x() - m_xMin) * m_plotRect.width() / (m_xMax - m_xMin);
    double y = m_plotRect.top() + (m_yMax - dataPos.y()) * m_plotRect.height() / (m_yMax - m_yMin);
    return QPointF(x, y);
}

// PlotSeries implementation
PlotSeries::PlotSeries(PlotWidget *parent)
    : QGraphicsPathItem()
    , m_plotWidget(parent)
    , m_style(Lines)
{
    setPen(QPen(Qt::blue, 1.0));
}

void PlotSeries::setTitle(const QString &title)
{
    m_title = title;
}

void PlotSeries::setPen(const QPen &pen)
{
    QGraphicsPathItem::setPen(pen);
}

void PlotSeries::setBrush(const QBrush &brush)
{
    QGraphicsPathItem::setBrush(brush);
}

void PlotSeries::setStyle(PlotStyle style)
{
    m_style = style;
}

void PlotSeries::setData(const QVector<QPointF> &data)
{
    m_data = data;
}

void PlotSeries::setData(const QVector<double> &xData, const QVector<double> &yData)
{
    m_data.clear();
    int count = qMin(xData.size(), yData.size());
    for (int i = 0; i < count; ++i) {
        m_data.append(QPointF(xData[i], yData[i]));
    }
}

void PlotSeries::setVisible(bool visible)
{
    QGraphicsPathItem::setVisible(visible);
}

void PlotSeries::updatePath(const QRectF &plotRect, const QRectF &dataRect)
{
    if (m_data.isEmpty() || !m_plotWidget) return;
    
    QPainterPath path;
    
    if (m_style == Bars) {
        // Draw vertical bars from x-axis (y=0) to each data point
        for (const QPointF &dataPoint : m_data) {
            QPointF scenePoint = m_plotWidget->mapFromData(dataPoint);
            QPointF basePoint = m_plotWidget->mapFromData(QPointF(dataPoint.x(), 0.0));
            
            // Draw vertical line from base (y=0) to the data point
            path.moveTo(basePoint);
            path.lineTo(scenePoint);
        }
    } else {
        // Default Lines style: connect points with continuous line
        bool firstPoint = true;
        
        for (const QPointF &dataPoint : m_data) {
            QPointF scenePoint = m_plotWidget->mapFromData(dataPoint);
            
            if (firstPoint) {
                path.moveTo(scenePoint);
                firstPoint = false;
            } else {
                path.lineTo(scenePoint);
            }
        }
    }
    
    setPath(path);
}

// PlotGrid implementation
PlotGrid::PlotGrid(PlotWidget *parent)
    : QGraphicsItem()
    , m_pen(QPen(Qt::gray, 0.5))
    , m_enabled(true)
    , m_isDarkTheme(false)
    , m_plotWidget(parent)
{
    setZValue(-1); // Draw behind curves
}

void PlotGrid::setPen(const QPen &pen)
{
    m_pen = pen;
    update();
}

void PlotGrid::setEnabled(bool enabled)
{
    m_enabled = enabled;
    setVisible(enabled);
}

QRectF PlotGrid::boundingRect() const
{
    return m_plotRect;
}

void PlotGrid::paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget)
{
    Q_UNUSED(option)
    Q_UNUSED(widget)
    
    if (!m_enabled) return;
    
    painter->setPen(m_pen);
    
    // Draw vertical grid lines
    int numVerticalLines = 10;
    for (int i = 0; i <= numVerticalLines; ++i) {
        double x = m_plotRect.left() + i * m_plotRect.width() / numVerticalLines;
        painter->drawLine(QPointF(x, m_plotRect.top()), QPointF(x, m_plotRect.bottom()));
    }
    
    // Draw horizontal grid lines
    int numHorizontalLines = 8;
    for (int i = 0; i <= numHorizontalLines; ++i) {
        double y = m_plotRect.top() + i * m_plotRect.height() / numHorizontalLines;
        painter->drawLine(QPointF(m_plotRect.left(), y), QPointF(m_plotRect.right(), y));
    }
}

void PlotGrid::updateGrid(const QRectF &plotRect, const QRectF &dataRect, bool isDarkTheme)
{
    m_plotRect = plotRect;
    m_dataRect = dataRect;
    m_isDarkTheme = isDarkTheme;
    update();
}

// PlotMarker implementation
PlotMarker::PlotMarker(PlotWidget *parent)
    : QGraphicsItem()
    , m_style(VLine)
    , m_pen(QPen(Qt::red, 1.0))
    , m_dataPos(0, 0)
    , m_plotWidget(parent)
{
}

void PlotMarker::setStyle(MarkerStyle style)
{
    m_style = style;
    update();
}

void PlotMarker::setPen(const QPen &pen)
{
    m_pen = pen;
    update();
}

void PlotMarker::setPosition(const QPointF &pos)
{
    prepareGeometryChange();
    m_dataPos = pos;
    update();
}

void PlotMarker::setLabel(const QString &label)
{
    m_label = label;
    update();
}

QRectF PlotMarker::boundingRect() const
{
    if (!m_plotWidget || m_plotRect.isEmpty()) return QRectF();
    
    QPointF scenePos = m_plotWidget->mapFromData(m_dataPos);
    
    // Only return the actual area occupied by the marker line (plus small margin)
    // This prevents unnecessary repainting of the entire plot
    const qreal margin = 2.0;
    
    switch (m_style) {
    case VLine:
        return QRectF(scenePos.x() - margin, m_plotRect.top(), 
                     margin * 2, m_plotRect.height());
    case HLine:
        return QRectF(m_plotRect.left(), scenePos.y() - margin,
                     m_plotRect.width(), margin * 2);
    case Cross:
        return m_plotRect; // Cross needs full area
    }
    
    return QRectF();
}

void PlotMarker::paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget)
{
    Q_UNUSED(option)
    Q_UNUSED(widget)
    
    if (!m_plotWidget) return;
    
    painter->setPen(m_pen);
    
    QPointF scenePos = m_plotWidget->mapFromData(m_dataPos);
    
    switch (m_style) {
    case VLine:
        painter->drawLine(QPointF(scenePos.x(), m_plotRect.top()), 
                         QPointF(scenePos.x(), m_plotRect.bottom()));
        break;
    case HLine:
        painter->drawLine(QPointF(m_plotRect.left(), scenePos.y()), 
                         QPointF(m_plotRect.right(), scenePos.y()));
        break;
    case Cross:
        painter->drawLine(QPointF(scenePos.x(), m_plotRect.top()), 
                         QPointF(scenePos.x(), m_plotRect.bottom()));
        painter->drawLine(QPointF(m_plotRect.left(), scenePos.y()), 
                         QPointF(m_plotRect.right(), scenePos.y()));
        break;
    }
    
    if (!m_label.isEmpty()) {
        QFont font = painter->font();
        QFontMetrics fm(font);
        QRect textRect = fm.boundingRect(m_label);
        QPointF textPos = scenePos + QPointF(5, -5);
        painter->drawText(textPos, m_label);
    }
}

void PlotMarker::updateMarker(const QRectF &plotRect, const QRectF &dataRect)
{
    m_plotRect = plotRect;
    m_dataRect = dataRect;
    update();
}

// PlotLegend implementation
PlotLegend::PlotLegend(PlotWidget *parent)
    : QGraphicsItem()
    , m_enabled(false)
    , m_plotWidget(parent)
{
    setZValue(1); // Draw on top
}

void PlotLegend::setEnabled(bool enabled)
{
    m_enabled = enabled;
    setVisible(enabled);
}

void PlotLegend::updateLegend(const QList<PlotSeries*> &series, const QRectF &plotRect)
{
    m_series = series;
    
    if (!m_enabled || series.isEmpty()) {
        m_boundingRect = QRectF();
        return;
    }
    
    // Calculate legend size
    QFont font;
    QFontMetrics fm(font);
    
    int maxWidth = 0;
    int totalHeight = 0;
    
    for (PlotSeries *s : series) {
        if (!s->title().isEmpty()) {
            int width = fm.horizontalAdvance(s->title()) + 30; // 30 for line sample
            maxWidth = qMax(maxWidth, width);
            totalHeight += fm.height() + 2;
        }
    }
    
    // Position legend in top-right corner
    m_boundingRect = QRectF(plotRect.right() - maxWidth - 10, 
                           plotRect.top() + 10,
                           maxWidth, totalHeight);
    
    update();
}

QRectF PlotLegend::boundingRect() const
{
    return m_boundingRect;
}

void PlotLegend::paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget)
{
    Q_UNUSED(option)
    Q_UNUSED(widget)
    
    if (!m_enabled || m_series.isEmpty()) return;
    
    // Draw legend background
    painter->fillRect(m_boundingRect, QColor(255, 255, 255, 200));
    painter->setPen(QPen(Qt::black, 1.0));
    painter->drawRect(m_boundingRect);
    
    QFont font;
    QFontMetrics fm(font);
    painter->setFont(font);
    
    int y = m_boundingRect.top() + 5;
    
    for (PlotSeries *series : m_series) {
        if (!series->title().isEmpty()) {
            // Draw line sample
            painter->setPen(series->pen());
            painter->drawLine(QPointF(m_boundingRect.left() + 5, y + fm.height()/2),
                             QPointF(m_boundingRect.left() + 25, y + fm.height()/2));
            
            // Draw text
            painter->setPen(QPen(Qt::black));
            painter->drawText(QPointF(m_boundingRect.left() + 30, y + fm.ascent()), series->title());
            
            y += fm.height() + 2;
        }
    }
}

// PlotAxisLabels implementation
PlotAxisLabels::PlotAxisLabels(PlotWidget *parent)
    : QGraphicsItem()
    , m_xMin(0), m_xMax(100), m_yMin(0), m_yMax(100)
    , m_yIntegerLabels(false)
    , m_isDarkTheme(false)
    , m_plotWidget(parent)
{
    setZValue(2); // Draw on top of grid but below curves
}

void PlotAxisLabels::updateLabels(const QRectF &plotRect, const QRectF &dataRect, 
                                  const QString &xTitle, const QString &yTitle,
                                  double xMin, double xMax, double yMin, double yMax,
                                  bool yIntegerLabels, bool isDarkTheme)
{
    m_plotRect = plotRect;
    m_xTitle = xTitle;
    m_yTitle = yTitle;
    m_xMin = xMin;
    m_xMax = xMax;
    m_yMin = yMin;
    m_yMax = yMax;
    m_yIntegerLabels = yIntegerLabels;
    m_isDarkTheme = isDarkTheme;
    update();
}

QRectF PlotAxisLabels::boundingRect() const
{
    // Expand beyond plot area to include space for labels
    return QRectF(0, 0, m_plotRect.right() + 50, m_plotRect.bottom() + 50);
}

void PlotAxisLabels::paint(QPainter *painter, const QStyleOptionGraphicsItem *option, QWidget *widget)
{
    Q_UNUSED(option)
    Q_UNUSED(widget)
    
    // Determine appropriate text color based on theme
    QColor axisColor = m_isDarkTheme ? Qt::white : Qt::black;
    
    painter->setPen(QPen(axisColor));
    QFont font = painter->font();
    font.setPointSize(9);
    painter->setFont(font);
    QFontMetrics fm(font);
    
    // Draw X-axis labels
    int numXTicks = 10;
    for (int i = 0; i <= numXTicks; ++i) {
        double dataX = m_xMin + (m_xMax - m_xMin) * i / numXTicks;
        double sceneX = m_plotRect.left() + m_plotRect.width() * i / numXTicks;
        
        // Draw tick mark
        painter->setPen(QPen(axisColor, 1));
        painter->drawLine(QPointF(sceneX, m_plotRect.bottom()), 
                         QPointF(sceneX, m_plotRect.bottom() + 5));
        
        // Draw label
        QString label = QString::number(dataX, 'f', 0);
        QRect textRect = fm.boundingRect(label);
        QPointF textPos(sceneX - textRect.width() / 2, 
                       m_plotRect.bottom() + 5 + textRect.height());
        painter->drawText(textPos, label);
    }
    
    // Draw Y-axis labels
    int numYTicks = 8;
    for (int i = 0; i <= numYTicks; ++i) {
        double dataY = m_yMin + (m_yMax - m_yMin) * i / numYTicks;
        double sceneY = m_plotRect.bottom() - m_plotRect.height() * i / numYTicks;
        
        // Draw tick mark
        painter->setPen(QPen(axisColor, 1));
        painter->drawLine(QPointF(m_plotRect.left() - 5, sceneY), 
                         QPointF(m_plotRect.left(), sceneY));
        
        // Draw label
        QString label = m_yIntegerLabels ? QString::number(qRound(dataY)) : QString::number(dataY, 'f', 1);
        QRect textRect = fm.boundingRect(label);
        QPointF textPos(m_plotRect.left() - 10 - textRect.width(), 
                       sceneY + textRect.height() / 4);
        painter->drawText(textPos, label);
    }
    
    // Draw X-axis title
    if (!m_xTitle.isEmpty()) {
        QRect titleRect = fm.boundingRect(m_xTitle);
        QPointF titlePos(m_plotRect.center().x() - titleRect.width() / 2,
                        m_plotRect.bottom() + 40);
        painter->drawText(titlePos, m_xTitle);
    }
    
    // Draw Y-axis title (rotated)
    if (!m_yTitle.isEmpty()) {
        painter->save();
        painter->translate(20, m_plotRect.center().y());
        painter->rotate(-90);
        QRect titleRect = fm.boundingRect(m_yTitle);
        painter->drawText(-titleRect.width() / 2, titleRect.height() / 2, m_yTitle);
        painter->restore();
    }
    
    // Draw plot border
    painter->setPen(QPen(axisColor, 1));
    painter->drawRect(m_plotRect);
}