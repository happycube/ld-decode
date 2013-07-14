#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

//#define CHZ 35795453.0 
//#define CHZ (28636363.0*5.0/4.0)

const double FSC=(1000000.0*(315.0/88.0))*1.00;
const double CHZ=(1000000.0*(315.0/88.0))*8.0;

using namespace std;

class LDE {
	protected:
		int order;
		const double *a, *b;
		double *y, *x;
	public:
		LDE(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			a = _a;
			b = _b;
			x = new double[order];
			y = new double[order];
	
			clear();
		}

		~LDE() {
			delete [] x;
			delete [] y;
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = val;
			}
		}

		double feed(double val) {
			for (int i = order - 1; i >= 1; i--) {
				x[i] = x[i - 1];
				y[i] = y[i - 1];
			}
		
			x[0] = val;
			y[0] = ((b[0] / a[0]) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			for (int o = 1; o < order; o++) {
				y[0] += ((b[o] / a[0]) * x[o]);
				y[0] -= ((a[o] / a[0]) * y[o]);
				//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
			}

			return y[0];
		}
		double val() {return y[0];}
};


unsigned double fbuf;


int main(int argc, char *argv[])
{
	int i, rv;
	double buf[1820];

	// XXX:  will fail horribly if read length isn't an even # of doubles
	while ((rv = read(0, &buf, 1820 * sizeof(double))) > 0) {
		double preout;	
		int nr = rv / sizeof(double);
		unsigned short out[nr];

		for (int i = 0; i < nr; i+=2) {
			preout = (buf[i] + buf[i + 1]) / 2;
#if 0
			preout = (preout * 800) + 4;
			if (preout < 16) preout = 16;
			if (preout > 1019) preout = 1019;
#else
			preout = (preout * 65536);
			if (preout < 0) preout = 0;
			if (preout > 65535) preout = 65535;
#endif
			out[i / 2] = preout; 
		} 
		write(1, out, 910 * 2);
	}

	return 0;
}
 
