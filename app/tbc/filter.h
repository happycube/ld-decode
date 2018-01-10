#ifndef FILTER_H
#define FILTER_H

#include <QCoreApplication>
#include <QDebug>
#include <vector>

class Filter
{
public:
    Filter(int _order, const double *_a, const double *_b);
    Filter(std::vector<double> _b, std::vector<double> _a);
    Filter(Filter *orig);

    void clear(double val);
    void dump();
    double feed(double val);
    double filterValue();

protected:
    int order;
    bool isIIR;
    std::vector<double> a, b;
    std::vector<double> y, x;
};

#endif // FILTER_H
