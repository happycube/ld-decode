/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <complex>
#include "ld-decoder.h"
#include "deemp.h"

double clamp(double v, double low, double high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

void aclamp(double *v, int len, double low, double high)
{
	for (int i = 0; i < len; i++) {
	        if (v[i] < low) v[i] = low;
		else if (v[i] > high) v[i] = high;
	}
}

// NTSC properties
const double in_freq = 8.0;	// in FSC.  Must be an even number!
#define OUT_FREQ 4
const double out_freq = OUT_FREQ;	// in FSC.  Must be an even number!

const double ntsc_uline = 63.5; // usec_
const double ntsc_ipline = 227.5 * in_freq; // pixels per line
const double ntsc_opline = 227.5 * out_freq; // pixels per line
const int ntsc_oplinei = 227.5 * out_freq; // pixels per line
const double dotclk = (1000000.0*(315.0/88.0)*in_freq); 

const double dots_usec = dotclk / 1000000.0; 

const double ntsc_blanklen = 9.2;

// we want the *next* colorburst as well for computation 
const double scale_linelen = ((63.5 + ntsc_blanklen) / 63.5); 

const double ntsc_ihsynctoline = ntsc_ipline * (ntsc_blanklen / 63.5);
const double iscale_tgt = ntsc_ipline + ntsc_ihsynctoline;

const double ntsc_hsynctoline = ntsc_opline * (ntsc_blanklen / 63.5);
const double scale_tgt = ntsc_opline + ntsc_hsynctoline;

const double phasemult = 1.591549430918953e-01 * in_freq;

// uint16_t levels
uint16_t level_m40ire = 1;
uint16_t level_0ire = 16384;
uint16_t level_7_5_ire = 16384+3071;
uint16_t level_100ire = 57344;
uint16_t level_120ire = 65535;

inline double u16_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -40 + ((160.0 / 65533.0) * (double)level); 
} 

inline uint16_t ire_to_u16(double ire)
{
	if (ire <= -60) return 0;
	if (ire <= -40) return 1;

	if (ire >= 120) return 65535;	

	return (((ire + 40) / 160.0) * 65534) + 1;
} 
		
// taken from http://www.paulinternet.nl/?page=bicubic
inline double CubicInterpolate(uint16_t *y, double x)
{
	double p[4];
	p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

	return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

inline void Scale(uint16_t *buf, double *outbuf, double start, double end, double outlen)
{
	double inlen = end - start;
	double perpel = inlen / outlen; 

	double p1 = start;
	for (int i = 0; i < outlen; i++) {
		int index = (int)p1;
		if (index < 1) index = 1;

		outbuf[i] = clamp(CubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

		p1 += perpel;
	}
}
                
inline double WrapAngle(double a1, double a2) {
	double v = a2 - a1;

	if (v > M_PIl) v -= (2 * M_PIl);
	else if (v <= -M_PIl) v += (2 * M_PIl);

	return v;
}

// tunables

double black_ire = 7.5;

int write_locs = -1;

uint16_t frame[505][(int)(OUT_FREQ * 213)];

// set up sync color heterodyne table first 
complex<double> burst_hdyne[2400];

Filter f_syncr(f_sync);
Filter f_synci(f_sync);

Filter f_bpcolor4(f_colorbp4);
Filter f_bpcolor8(f_colorbp8);
		
void BurstDetect(double *line, int freq, double _loc, double &plevel, double &pphase) 
{
	double _cos[freq], _sin[freq];
	double pi = 0, pq = 0, ploc = -1;
	int len = (25 * freq);
	int loc = _loc * freq;

	Filter *f_bpcolor;

	plevel = 0.0;
	pphase = 0.0;

	f_syncr.clear(0);
	f_synci.clear(0);
	
	for (int e = 0; e < freq; e++) {
		_cos[e] = cos((2.0 * M_PIl * ((double)e / freq)));
		_sin[e] = sin((2.0 * M_PIl * ((double)e / freq)));
	}

	if (freq == 4) {
		f_bpcolor = &f_bpcolor4;
	} else {
		f_bpcolor = &f_bpcolor8;
	}
	f_bpcolor->clear(0);

	for (int l = loc + (14 * freq); l < loc + len; l++) {
		double v = f_bpcolor->feed(line[l]);

		double q = f_syncr.feed(v * _cos[l % freq]);
		double i = f_synci.feed(-v * _sin[l % freq]);

		double level = ctor(i, q);

	//	cerr << l << ' ' << line[l] << ' ' << v << ' ' << i << ' ' << q << ' ' << level << ' ' << atan2(i, q) << endl;

		if (((l - loc) > 16) && (level > plevel) && (level < 10000)) {
			ploc = l;
//			cerr << l << ' ' << level << ' ' << atan2(pi, pq) << endl;
			plevel = level;
			pi = i; pq = q;
		}
	}

	if (plevel) {
		pphase = atan2(pi, pq);
	}
}
	
int get_oline(double line)
{
	int l = (int)(line + 0.5);

	if (l < 10) return -1;
	else if (l < 262) return (l - 10) * 2;
	else if (l < 271) return -1;
	else if (l < 525) return ((l - 273) * 2) + 1;

	return -1;
}

Filter f_syncp(f_sync);
double cross = 5000;

double line = -2;
double tgt_phase = 0;

int Process(uint16_t *buf, int len)
{
	double prevf, f = 0;
	double crosspoint = -1, prev_crosspoint = -1, tmp_crosspoint = -1;
	int count = 0;
	int firstline = -1;

	f_syncp.clear(ire_to_u16(black_ire));

	for (int i = 0; i < len - 2048; i++) {
		prevf = f;
		f = f_syncp.feed(buf[i]); 
	
		if (f < cross) {
			if (count <= 0) {
				double d = prevf - f;
				double c = (prevf - cross) / d;

				tmp_crosspoint = (i - 1) + c; 
			}
			count++;
		} else {
			if (count > 40) crosspoint = tmp_crosspoint;

			if ((count > 30) && prev_crosspoint > 0) {
				double begin = prev_crosspoint;
				double end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
				double linelen = crosspoint - prev_crosspoint; 

				double tout1[4096], tout2[4096], tout3[4096];

				cerr << line << ' ' << i << ' ' << linelen << ' ' << count << endl;
				if ((line >= 0) && (linelen >= (ntsc_ipline * 0.9)) && (count > (11 * in_freq))) {
					// standard line
					double plevel1, pphase1;
					double plevel2, pphase2;
					double adjust1, adjust2;
					int oline = get_oline(line);

					if (firstline < 0) firstline = line;

					Scale(buf, tout1, begin, end, scale_tgt); 
					BurstDetect(tout1, out_freq, 0, plevel1, pphase1); 
					BurstDetect(tout1, out_freq, 228, plevel2, pphase2); 

					if (!tgt_phase) {
						if ((pphase1 < 0) && (pphase1 > (-M_PIl * 3 / 4))) {
							tgt_phase = (-M_PIl / 2.0);
						} else {
							tgt_phase = (M_PIl / 2.0);
						}
					} else tgt_phase = -tgt_phase;
			
					if (floor(line) == 272) tgt_phase = -tgt_phase;

					double atgt_phase = tgt_phase - (57 * (M_PIl / 180));

					if (tgt_phase > 0) 
						atgt_phase = (-180 + 0) * (M_PIl / 180);
					else
						atgt_phase = (0 + 0) * (M_PIl / 180);

			//		atgt_phase = tgt_phase + (33 * (M_PIl / 180));

					cerr << line << " 0" << ' ' << ((end - begin) / scale_tgt) * 1820.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
					adjust1 = WrapAngle(pphase1, atgt_phase);	
					adjust2 = WrapAngle(pphase2, atgt_phase);
					begin += (adjust1 * phasemult);
					end += (adjust1 * phasemult);

					Scale(buf, tout2, begin, end, scale_tgt); 
					BurstDetect(tout2, out_freq, 0, plevel1, pphase1); 
					BurstDetect(tout2, out_freq, 228, plevel2, pphase2); 
					
					cerr << line << " 1" << ' ' << ((end - begin) / scale_tgt) * 1820.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;

					adjust1 = WrapAngle(pphase1, atgt_phase);	
					adjust2 = WrapAngle(pphase2, pphase1);
					end += (adjust2 * phasemult);
					
					Scale(buf, tout3, begin, end, scale_tgt); 
					BurstDetect(tout3, out_freq, 0, plevel1, pphase1); 
					BurstDetect(tout3, out_freq, 228, plevel2, pphase2); 

					cerr << line << " 2" << ' ' << ((end - begin) / scale_tgt) * 1820.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
					
					// LD only: need to adjust output value for velocity
					double lvl_adjust = ((((end - begin) / iscale_tgt) - 1) * 0.84) + 1;
					int ldo = -128;
					for (int i = 0; (oline > 0) && (i < (213 * out_freq)); i++) {
						double v = tout3[i + (int)(14 * out_freq)];

						v = ((v / 57344.0) * 1700000) + 7600000;
						v *= lvl_adjust;
						v = ((v - 7600000) / 1700000) * 57344.0;

						if ((v < 3000) && (i > 16)) ldo = i;

						if (((i - ldo) < 16) && (i > 4) && (oline >= 4)) {
							v = frame[oline - 2][i - 2];
						}

//						cerr << tout3[x] << ' ' << v << endl;
						frame[oline][i] = clamp(v, 0, 65535);
//						cerr << x << ' ' << tout1[x] << ' ' << tout2[x] << ' ' << tout3[x] << ' ' << v << ' ' << frame[oline][x - (int)(14 * out_freq)] << endl;
					}

					if (tgt_phase > 0) 
						frame[oline][0] = 32768; 
					else
						frame[oline][0] = 16384; 
					
					//crosspoint = begin + (((end - begin) / scale_tgt) * 1820);
	
					line++;
				} else if ((line == -1) && (linelen > 800) && (linelen < 1000) && (count > 80) && (count < 160)) {
					line = 262.5;
				} else if (((line == -1) || (line > 520)) && (linelen > 1800) && (count < 80)) {
					if (line > 0) {
						write(1, frame, sizeof(frame));
					}
					tgt_phase = 0;
					line = 1;
					firstline = -1;
				} else if ((line == -2) && (linelen > 1800) && (count > 80)) {
					line = -1;
				} else if ((line >= 0) && (linelen > 800) && (linelen < 1000)) {
					line += 0.5;
				} else if ((line >= 0) && (linelen > 1700)) {
					line += 1;
				} 
//				printerr(line, prev_crosspoint, crosspoint, count)
 
	//			if (floor(line) == 272) tgt_phase -= tgt_phase;
//				cerr << line << endl;
			}

			prev_crosspoint = crosspoint;

			count = 0;
		}
	}

	return (prev_crosspoint - 700);
}

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1, tproc = 0;
	//double output[2048];
	unsigned short inbuf[16384];
	unsigned char *cinbuf = (unsigned char *)inbuf;

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	if (argc >= 2 && (strncmp(argv[1], "-", 1))) {
		fd = open(argv[1], O_RDONLY);
	}

	if (argc >= 3) {
		unsigned long long offset = atoll(argv[2]);

		if (offset) lseek64(fd, offset, SEEK_SET);
	}
		
	if (argc >= 4) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	for (int i = 0; i < 2400; i++) {
		 burst_hdyne[i] = complex<double>(cos(((i / in_freq) * 2.0 * M_PIl) + (0.0/180.0)), -(sin(((i / in_freq) * 2.0 * M_PIl) + (0.0/180.0))));
	}

	// XX: make parameter
	#if SOUND
		write_locs = 0;
	#endif

	cout << std::setprecision(8);

	rv = read(fd, inbuf, 32768);
	while ((rv > 0) && (rv < 32768)) {
		int rv2 = read(fd, &cinbuf[rv], 32768 - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	while (rv == 32768 && ((tproc < dlen) || (dlen < 0))) {
		int plen = Process(inbuf, rv / 2);	

		tproc += plen;
                memmove(inbuf, &inbuf[plen], (16384 - plen) * 2);
                rv = read(fd, &inbuf[(16384 - plen)], plen * 2) + ((16384 - plen) * 2);
		while ((rv > 0) && (rv < 32768)) {
			int rv2 = read(fd, &cinbuf[rv], 32768 - rv);
			if (rv2 <= 0) exit(-1);
			rv += rv2;
		}	
	}

	return 0;
}

