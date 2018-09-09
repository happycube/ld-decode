/* very rough frequency sweep (1-49mhz) to use with osmo_fl2k.
 * 
 * usage:
 *
 * gcc -O2 -o siggen siggen.c -lm
 * ./siggen > /dev/shm/signal.raw
 *
 * then
 * fl2k_file -r 1 /dev/shm/signal.raw
 *
 */ 

#include <stdio.h>
#include <sys/fcntl.h>
#include <math.h>
#include <unistd.h>

const int SPS = 100000000;

const double lowfreq  = 1000000;
const double highfreq = 49000010;

const double freqgap = 1000000;
const int freqtime = 10000000; 

double level = 60;

char buf[4096 * 3];

#define PI 3.14159265358979

int main(void)
{
	int snum = 0;
	int ba, bufloc = 0;

	double phase = 0;

	double time;
	double freq = lowfreq;

	while (freq < highfreq) {
		phase += (2 * PI * (freq / (double)SPS));
		if (phase > (2 * PI)) phase -= (2 * PI);
		
		char output = (char)((sin(phase) * level) + 0); 
		buf[bufloc++] = output;

		if (bufloc == sizeof(buf)) {
			write(1, buf, sizeof(buf));
			bufloc = 0;
		}

		snum++;
		if (!(snum % freqtime)) {
			freq += freqgap;
		}
			
	}
}

