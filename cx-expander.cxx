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

/* 
 *  Key CX notes for decoding:
 *  
 *  - CX expanding crosses over/is equal at 0 DB (40% modulation) - this is found on Pioneer ref disk 
 *
 *  - Per PR-8210 service manual, at 75% modulation should be 87.3% higher (914mVrms vs 488mVrms)
 */

void Process(uint16_t *buf, int nsamp)
{
	for (int i = 0; i < nsamp; i++) {
		double left = (buf[i * 2] - 32768); 
		double right = (buf[(i * 2 + 1)] - 32768); 

		snum++;

		double orig_left = left;
		double orig_right = right;

		left = (f_left.feed(left));
		right = (f_right.feed(right));

		double _max = max(fabs(left), fabs(right));

//		if ((snum < 100) || (snum > 2000)) _max = 0; 
//		if ((snum < 100)) _max = 0; 

//		fast = (fast * .96) + (_max * .04);	
		fast = (fast * .9998);
		if (_max > fast) fast = min(_max, fast + (_max * .040));	
	
//		cerr << snum << " IN " << left << ' ' << right << ' ' ;

		slow = (slow * .999985);
		if (_max > slow) slow = min(_max, slow + (_max * .0020));	

		const double factor = 6500;

		// XXX : there is currently some non-linearity in 1khz samples
		double val = max(fast, slow * 1.00) - (factor * m14db);

		if (val < 0) val = 0;

		// 7200-1500=5500 is the (current) 0db point for val

		left = orig_left * m14db;
		right = orig_right * m14db;

		left *= 1 + (val / (factor * m14db));
		right *= 1 + (val / (factor * m14db));

//		cerr << ' ' << _max << " F:" << fast << " S:" << slow << ' ' << val << " OUT " << left << ' ' << right << ' ' << left / orig_left << ' ' << right / orig_right << endl;

		// need to reduce it to prevent clipping 
		left *= .25;
		right *= .25;
	
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


