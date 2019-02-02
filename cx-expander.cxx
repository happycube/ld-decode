#include <unistd.h>
#include <stdio.h>
#include <iostream>
#include "ld-decoder.h"
#include "deemp.h"

using namespace std;

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
double m22db = 0.07943282347242814; // 10 ** (-22 / 20)

/* 
 *  Key CX notes for decoding:
 *  
 *  - CX expanding crosses over/is equal at 0 DB (40% modulation) - this is found on Pioneer ref disk 
 *
 *  - Per PR-8210 service manual, at 75% modulation should be 87.3% higher (914mVrms vs 488mVrms)
 */

void Process(int16_t *buf, int nsamp)
{
	int16_t obuf[nsamp * 2];

	//cerr << fast << ' ' << slow << endl;

	for (int i = 0; i < nsamp; i++) {
		double left = (buf[i * 2] ); 
		double right = (buf[(i * 2 + 1)] ); 

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

		// approximate 0dB point using ld-decode rev4
		const double s0db = 15250;
		//const double sm22db = s0db * m22db;

		double val = max(fast, slow * 1.00) / s0db;

		if (val < m22db) val = m22db;

		left = orig_left * val;
		right = orig_right * val;

		if (0 && i == 0) {
			cerr << orig_left << ' ' << max(fast, slow * 1.00) << ' ' << val << ' ' << left << endl;
		}

		//left *= 1 + (val / (factor * m28db));
		//right *= 1 + (val / (factor * m28db));

//		left = f_left30.feed(left);
//		right = f_right30.feed(right);

//		cerr << ' ' << _max << " F:" << fast << " S:" << slow << ' ' << val << " OUT " << left << ' ' << right << ' ' << left / orig_left << ' ' << right / orig_right << endl;

		// need to reduce it to prevent clipping 
		//left *= .55;
		//right *= .55;
	
		obuf[(i * 2)] = clamp(left, -32767, 32767);
		obuf[(i * 2) + 1] = clamp(right, -32767, 32767);
	}
	write(1, obuf, nsamp * 4);
}

// 1024 samples, 2 channels, 2 bytes/sample
const int blen = 1024;

int16_t inbuf[blen * 2];
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


