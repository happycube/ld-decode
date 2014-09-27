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

bool audio_only = false;

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

bool InRange(double v, double l, double h) {
	return ((v > l) && (v < h));
}

// tunables

bool write_fields = false;
bool despackle = true;
int afd = -1, fd = 0;

double black_ire = 7.5;

int write_locs = -1;

uint16_t frame[505][(int)(OUT_FREQ * 211)];

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
		int x = line[l];
	
		if (x < 6000) x = 6000;
		if (x >= 26000) x = 26000;

		double v = f_bpcolor->feed(x);

		double q = f_syncr.feed(v * _cos[l % freq]);
		double i = f_synci.feed(-v * _sin[l % freq]);

		double level = ctor(i, q);

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
	int l = (int)line;

	if (l < 10) return -1;
	else if (l < 262) return (l - 10) * 2;
	else if (l < 271) return -1;
	else if (l < 525) return ((l - 273) * 2) + 1;

	return -1;
}

double pleft = 0, pright = 0;
double _left = 0, _right = 0;
Filter f_fml(f_fmdeemp), f_fmr(f_fmdeemp);

uint16_t aout[512];
int aout_i = 0;
void ProcessAudioSample(float left, float right)
{
	float oleft = left, oright = right;

	if (!InRange(left, 2150000, 2450000)) left = pleft;
	pleft = left;
	left -= 2301136;
	left *= (65535.0 / 300000.0);
	left = f_fml.feed(left);
	left += 32768;
	
	if (!InRange(right, 2650000, 2960000)) right = pright;
	pright = right;
	right -= 2812499;
	right *= (65535.0 / 300000.0);
	right = f_fmr.feed(right);
	right += 32768;

	cerr << "P1 " << oleft << ' ' << left - _left << ' ' << oright << ' ' << right - _right << endl;
	_left = left;
	_right = right;

	aout[aout_i * 2] = clamp(left, 0, 65535);
	aout[(aout_i * 2) + 1] = clamp(right, 0, 65535);
	
//	cerr << "P2 " << aout[aout_i * 2] << ' ' << aout[(aout_i * 2) + 1] << endl;

	aout_i++;
	if (aout_i == 256) {
		int rv = write(audio_only ? 1 : 3, aout, sizeof(aout));

		rv = aout_i = 0;
	}
}

Filter f_syncp(f_sync);
double cross = 5000;

double line = -2;
int phase = -1;

int64_t vread = 0, aread = 0;
int va_ratio = 80;
	
double a_next = -1;
double afreq = 48000;
double agap  = dotclk / (double)va_ratio;

bool first = true;
double prev_linelen = 1820;


void ProcessLine(uint16_t *buf, double begin, double end, int line)
{
	double tout1[4096], tout2[4096], tout3[4096];
	double plevel1, pphase1;
	double plevel2, pphase2;
	double adjust1, adjust2;
	int oline = get_oline(line);

	double tgt_phase;

	Scale(buf, tout1, begin, end, scale_tgt); 
	BurstDetect(tout1, out_freq, 0, plevel1, pphase1); 
	BurstDetect(tout1, out_freq, 228, plevel2, pphase2); 

	if (plevel1 < 1000) goto wrapup;
	if (plevel2 < 1000) goto wrapup;

	if (phase == -1) {
		phase = (fabs(pphase1) > (M_PIl / 2));
		tgt_phase = ((line + phase) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));
		cerr << "p " << pphase1 << ' ' << fabs(pphase1) << ' ' << phase << ' ' << tgt_phase << endl;
	} 

	tgt_phase = ((line + phase) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));

//	cerr << line << " 0" << ' ' << ((end - begin) / scale_tgt) * 1820.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
	cerr << line << " 0" << ' ' << begin << ' ' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
	adjust1 = WrapAngle(pphase1, tgt_phase);	
	adjust2 = WrapAngle(pphase2, pphase1);
	begin += (adjust1 * phasemult);
	end += ((adjust1 + adjust2) * phasemult);

	Scale(buf, tout2, begin, end, scale_tgt); 
	BurstDetect(tout2, out_freq, 0, plevel1, pphase1); 
	BurstDetect(tout2, out_freq, 228, plevel2, pphase2); 
					
	cerr << line << " 1" << ' ' << begin << ' ' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;

	adjust1 = WrapAngle(pphase1, tgt_phase);	
	adjust2 = WrapAngle(pphase2, pphase1);
	begin += (adjust1 * phasemult);
	end += ((adjust1 + adjust2) * phasemult);

//	adjust2 = WrapAngle(pphase2, pphase1);
//	end += (adjust2 * phasemult);
					
	Scale(buf, tout3, begin, end, scale_tgt); 
	BurstDetect(tout3, out_freq, 0, plevel1, pphase1); 
	BurstDetect(tout3, out_freq, 228, plevel2, pphase2); 

	cerr << line << " 2" << ' ' << begin << ' ' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;

wrapup:
	// LD only: need to adjust output value for velocity, and remove defects as possible
	double lvl_adjust = ((((end - begin) / iscale_tgt) - 1) * 1.0) + 1;
	int ldo = -128;
	for (int i = 0; (oline > 2) && (i < (211 * out_freq)); i++) {
		double v = tout3[i + (int)(14 * out_freq)];

		v = ((v / 57344.0) * 1700000) + 7600000;
		double o = (((v * lvl_adjust) - 7600000) / 1700000) * 57344.0;

		if (despackle && (v < 7800000) && (i > 16)) {
			if ((i - ldo) > 16) {
				for (int j = i - 4; j > 2 && j < i; j++) {
					double to = (frame[oline - 2][j - 2] + frame[oline - 2][j + 2]) / 2;
					frame[oline][j] = clamp(to, 0, 65535);
				}
			}
			ldo = i;
		}

		if (((i - ldo) < 16) && (i > 4)) {
			o = (frame[oline - 2][i - 2] + frame[oline - 2][i + 2]) / 2;
		}

		frame[oline][i] = clamp(o, 0, 65535);
	}
	
	frame[oline][0] = tgt_phase ? 32768 : 16384; 
}

bool IsABlank(int line, double start, double len)
{
	bool isHalf = false;
	double end = start + len;

	double half = 227.5 * in_freq / 2;
	double full = 227.5 * in_freq;

	if ((line == 525) || (line < 10) || ((line >= 263) && (line <272))) isHalf = true;

	if (end > full) return true;
	if (isHalf && (end > half)) return true;

	return false;
}

int Process(uint16_t *buf, int len, float *abuf, int alen, int &aplen)
{
	double prevf, f = 0;
	double crosspoint = -1, prev_crosspoint = -1, tmp_crosspoint = -1;
	int prev_count = 0, count = 0, debounce = 0;
	int rv = 0;
	bool valid;

	double prev_linelen = 1820;

	f_syncp.clear(ire_to_u16(black_ire));

	cerr << "Process " << len << ' ' << (const void *)buf << endl;
	f_syncp.dump();

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
			debounce = 0;
		} else {
			double bkup_crosspoint = crosspoint;

			if (debounce < 16) debounce++;

			if ((debounce >= 16) && (count > 40)) crosspoint = tmp_crosspoint;

			if ((debounce >= 16) && (count > 40) && prev_crosspoint > 0) {
				double begin = prev_crosspoint;
				double end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
				double linelen = crosspoint - prev_crosspoint; 
				
				int oline = get_oline(line + 0);

				cerr << "S " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << endl;

				valid = IsABlank(line, crosspoint - prev_crosspoint, count); 

				if (!valid) {
					cerr << "X " << crosspoint - prev_crosspoint << ' ' << count << endl;

					crosspoint = bkup_crosspoint;
					debounce = 0;
					count = 0;
					continue;
				}
		
				double algap = fabs(linelen - prev_linelen);
				int acgap = abs(count - prev_count);	
				double lgap = (linelen - prev_linelen);
				int cgap = (count - prev_count);	
				bool eed = false;
	
				if (prev_count && (get_oline(line) >= 0) && (get_oline(line + 1) >= 0) && (InRange(algap, 4, 100) || InRange(acgap, 2, 100))) {
					cerr << "E " << begin << ' ' << crosspoint << ' ' << end << ' ' << linelen << ' ' << prev_linelen << ' ' << prev_count << ' ' << count << endl;

					eed = true;

					cerr << linelen << ' ' << count - prev_count << endl;

					if (InRange(linelen + (count - prev_count), 1818, 1822)) {
						cerr << "C " << endl;
						crosspoint -= (linelen - prev_linelen);
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} else if (0 && prev_count && (count > prev_count)) {
						cerr << "D " << endl;
						crosspoint -= (linelen - prev_linelen);
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} else if (0 && (crosspoint - prev_crosspoint) < (prev_linelen - 4)) {
						cerr << "A " << endl;
						crosspoint -= (linelen - prev_linelen);
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} else if (1) {
						cerr << "B " << endl;
						begin += (linelen - prev_linelen);
						prev_crosspoint += (linelen - prev_linelen);
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} 

					cerr << "ES " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << endl;
				}	

				prev_count = count;

				if ((line >= 0) && (linelen >= (ntsc_ipline * 0.9)) && (count > (11 * in_freq))) {
					// standard line
					int oline = get_oline(line);

					if (oline >= 0) {
						ProcessLine(buf, begin, end, line); 
	
						if (0 && eed == true) {
							for (int i = 1; i < 65; i++) 
								frame[oline][i] = 65535; 
						}
					}	

					prev_linelen = linelen;					

					double tmplen = linelen;
					while (tmplen > 850) {
						line = line + 0.5;
						tmplen -= 910;
					}
					//crosspoint = begin + (((end - begin) / scale_tgt) * 1820);
				} else if ((line == -1) && InRange(linelen, 850, 950) && InRange(count, 40, 160)) {
					line = 262.5;
					prev_linelen = 1820;					
				} else if (((line == -1) || (line > 520)) && (linelen > 1800) && InRange(count, 40, 75)) {
					if (!first) {
						write(1, frame, sizeof(frame));
						memset(frame, 0, sizeof(frame));
					} else first = false;
					prev_linelen = 1820;					
					line = 1;
					if (phase >= 0) phase = !phase;
				} else if ((line == -2) && (linelen > 1780) && (count > 80)) {
					line = -1;
				} else if (line >= 0) {
					double tmplen = linelen;
					while (tmplen > 850) {
						line = line + 0.5;
						tmplen -= 910;
					}
				} 

				if (write_fields && line == 268) {
					if (!first) {
						write(1, frame, sizeof(frame));
						memset(frame, 0, sizeof(frame));
					} else first = false;
				}
 
				// process audio (if available)
				if ((afd > 0) && (line > 0)) {
					double nomlen = InRange(linelen, 850, 950) ? 910 : 1820;
					double scale = linelen / nomlen;
					
					double lvl_adjust = ((scale - 1) * 0.84) + 1;

					if (a_next < 0) a_next = prev_crosspoint / va_ratio;
						
					cerr << "a" << a_next * va_ratio << ' ' << crosspoint << endl; 
					while ((a_next * va_ratio) < crosspoint) {
						int index = (int)a_next * 2;

						float left = abuf[index], right = abuf[index + 1];
						
						ProcessAudioSample(left * lvl_adjust, right * lvl_adjust);
	
						aplen = a_next;
						a_next += ((dotclk / afreq) / va_ratio) * scale;
					}	
				}	
			} else if (prev_crosspoint < 0) {
				prev_count = count;
			}

			if (debounce >= 16) { 
				prev_crosspoint = crosspoint;
				count = 0;
			}
		}
	}
	
	rv = prev_crosspoint - 200;

	a_next -= aplen;
	aplen *= 2;
	cerr << "N " << a_next << endl;
	vread += rv;

	return rv;
}

const int ablen = 8192;
const int vblen = ablen * 16;

const int absize = ablen * 8;
const int vbsize = vblen * 2;

int main(int argc, char *argv[])
{
	int rv = 0, arv = 0;
	long long dlen = -1, tproc = 0;
	float abuf[ablen * 2];
	unsigned short inbuf[vblen];
	unsigned char *cinbuf = (unsigned char *)inbuf;
	unsigned char *cabuf = (unsigned char *)abuf;

	int c;

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "s:n:i:a:Af")) != -1) {
		switch (c) {
			case 's':
				sscanf(optarg, "%lf", &cross);
				break;
			case 'i':
				fd = open(optarg, O_RDONLY);
				break;
			case 'a':
				afd = open(optarg, O_RDONLY);
				break;
			case 'A':
				audio_only = true;
				break;
			case 'n':
				despackle = false;
				break;
			case 'f':
				write_fields = true;
				break;
			default:
				return -1;
		} 
	} 

	cout << std::setprecision(8);

	rv = read(fd, inbuf, vbsize);
	while ((rv > 0) && (rv < vbsize)) {
		int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	if (afd != -1) {	
		arv = read(afd, abuf, absize);
		while ((arv > 0) && (arv < absize)) {
			int arv2 = read(fd, &cabuf[arv], absize - arv);
			if (arv2 <= 0) exit(0);
			arv += arv2;
		}
	}

	int aplen = 0;
	while (rv == vbsize && ((tproc < dlen) || (dlen < 0))) {
		int plen = Process(inbuf, rv / 2, abuf, arv / 8, aplen);

		cerr << "plen " << plen << endl;
		tproc += plen;
               
		memmove(inbuf, &inbuf[plen], (vblen - plen) * 2);
	
                rv = read(fd, &inbuf[(vblen - plen)], plen * 2) + ((vblen - plen) * 2);
		while ((rv > 0) && (rv < vbsize)) {
			int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}	
		
		
		if (afd != -1) {	
			cerr << "X" << aplen << ' ' << (double)(ablen - (aplen * 4))/4.0 << ' ' << abuf[0] << ' ' ;
			memmove(abuf, &abuf[aplen], absize - (aplen * 4));
			cerr << abuf[0] << endl;

                	arv = read(afd, &abuf[ablen - aplen], aplen * 4) + (absize - (aplen * 4));
			while ((arv > 0) && (arv < absize)) {
				int arv2 = read(afd, &cabuf[arv], absize - arv);
				if (arv2 <= 0) exit(0);
				arv += arv2;
			}
		}
	}

	return 0;
}
