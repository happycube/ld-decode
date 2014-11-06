#include <unistd.h>
#include <stdio.h>
#include <iostream>
#include "ld-decoder.h"
#include "deemp.h"

using namespace std;

const double freq = 48000.0;

double clamp(double v, double low, double high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

Filter f_left(f_a500_48k), f_left30(f_a40h_48k);
Filter f_right(f_a500_48k), f_right30(f_a40h_48k);

int snum = 0;
double slow = 0, fast = 0;

double m14db = 0.199526231496888;

void Process(uint16_t *buf, int nsamp)
{

	for (int i = 0; i < nsamp; i++) {
		double left = (buf[i * 2] - 32768); 
		double right = (buf[(i * 2 + 1)] - 32768); 

		snum++;
//		cerr << snum << ' ' << left << ' ' << right << ' ' ;

		left = (f_left.feed(left));
		right = (f_right.feed(right));

		double _max = max(fabs(left), fabs(right));

//		if ((snum < 100) || (snum > 2000)) _max = 0; 

//		fast = (fast * .96) + (_max * .04);	
		fast = (fast * .998);
		if (_max > fast) fast = min(_max, fast + (_max * .032));	
		
//		cerr << left << ' ' << right << ' ' << _max << ' ';

		slow = (slow * .99985);
		if (_max > slow) slow = min(_max, slow + (_max * .0019));	

		double val = max(fast, slow * 1.00) - (7200 * m14db);

		if (val < 0) val = 0;

		// 7200-1500=5500 is the (current) 0db point for val

		left *= m14db;
		right *= m14db;

		left *= 1 + (val / 1250);
		right *= 1 + (val / 1250);
	
//		cerr << ' ' << _max << ' ' << fast << ' ' << slow << ' ' << val << ' ' << left << ' ' << right << endl;

		uint16_t obuf[2];

		obuf[0] = clamp(left + 32768, 0, 65535);
		obuf[1] = clamp(right + 32768, 0, 65535);
		write(1, obuf, 4);
	}
}

// 1024 samples, 2 channels, 2 bytes/sample
const int blen = 1024;

uint16_t inbuf[blen * 2];
unsigned char *cinbuf = (unsigned char *)inbuf;

int main(int argc, char *argv[])
{
	int rv = 0;
	int fd = 0;

	do { 
		rv = read(fd, inbuf, sizeof(inbuf));
		if (rv <= 0) exit(0);

		while (rv < sizeof(inbuf)) {
			int rv2 = read(fd, &cinbuf[rv], sizeof(inbuf) - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}

		Process(inbuf, blen);
	} while (1);
}


