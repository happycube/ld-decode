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
#ifdef FSC10
const double in_freq = 10.0;	// in FSC.  Must be an even number!
#elif defined(FSC4)
const double in_freq = 4.0;	// in FSC.  Must be an even number!
#else
const double in_freq = 8.0;	// in FSC.  Must be an even number!
#endif

#define OUT_FREQ 4
const double out_freq = OUT_FREQ;	// in FSC.  Must be an even number!

//const double ntsc_uline = 63.5; // usec_
const double ntsc_iphline = 113.75 * in_freq; // pixels per half-line
const double ntsc_ipline = 227.5 * in_freq; // pixels per line
const double ntsc_opline = 227.5 * out_freq; // pixels per line
//const int ntsc_oplinei = 227.5 * out_freq; // pixels per line
const double dotclk = (1000000.0*(315.0/88.0)*in_freq); 

//const double dots_usec = dotclk / 1000000.0; 

const double ntsc_blanklen = 9.2;

// we want the *next* colorburst as well for computation 
const double scale_linelen = ((63.5 + ntsc_blanklen) / 63.5); 

const double ntsc_ihsynctoline = ntsc_ipline * (ntsc_blanklen / 63.5);
const double iscale_tgt = ntsc_ipline + ntsc_ihsynctoline;

const double ntsc_hsynctoline = ntsc_opline * (ntsc_blanklen / 63.5);
const double scale_tgt = ntsc_opline + ntsc_hsynctoline;

const double phasemult = 1.591549430918953e-01 * in_freq;

// uint16_t levels
uint16_t level_m40ire;
uint16_t level_0ire;
uint16_t level_7_5_ire;
uint16_t level_100ire;
uint16_t level_120ire;

bool audio_only = false;

double inbase = 1;	// IRE == -60
double inscale = 327.68;

inline double in_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -60 + ((double)(level - inbase) / inscale); 
} 

inline uint16_t ire_to_in(double ire)
{
	if (ire <= -60) return 0;
	
	return clamp(((ire + 60) * inscale) + inbase, 1, 65535);
} 

inline uint16_t ire_to_out(double ire)
{
	if (ire <= -60) return 0;
	
	return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}
		
// taken from http://www.paulinternet.nl/?page=bicubic
double CubicInterpolate(uint16_t *y, double x)
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
                
bool InRange(double v, double l, double h) {
	return ((v > l) && (v < h));
}

bool InRangeCF(double v, double l, double h) {
	l *= in_freq;
	h *= in_freq;
	return ((v > l) && (v < h));
}

// tunables

bool write_fields = false;
bool despackle = true;
int afd = -1, fd = 0;

double black_ire = 7.5;

int write_locs = -1;

uint16_t frame[505][(int)(OUT_FREQ * 211)];

Filter f_bpcolor4(f_colorbp4);
Filter f_bpcolor8(f_colorbp8);

#ifdef FSC10
Filter f_syncr(f_sync10);
Filter f_synci(f_sync10);

Filter f_syncp(f_sync10);

Filter f_longsync(f_dsync10);
#elif defined(FSC4)
Filter f_syncr(f_sync4);
Filter f_synci(f_sync4);

Filter f_syncp(f_sync4);

Filter f_longsync(f_dsync4);
#else
Filter f_syncr(f_sync);
Filter f_synci(f_sync);

Filter f_syncp(f_sync);

Filter f_longsync(f_dsync);
#endif
		
void BurstDetect(double *line, int freq, double _loc, double &plevel, double &pphase) 
{
	double _cos[freq], _sin[freq];
	double pi = 0, pq = 0, ploc = -1;
	int len = (28 * freq);
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

	for (int l = loc + (15 * freq); l < loc + len; l++) {
		int x = line[l];
	
		if (x < 6000) x = 6000;
		if (x >= 26000) x = 26000;

		double v = f_bpcolor->feed(x);

		double q = f_syncr.feed(v * _cos[l % freq]);
		double i = f_synci.feed(-v * _sin[l % freq]);

		double level = ctor(i, q);

//		cerr << l << ' ' << level << ' ' << atan2(pi, pq) << endl;

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

	if (l < 9) return -1;
	else if (l < 262) return (l - 9) * 2;
	else if (l < 272) return -1;
	else if (l < 524) return ((l - 272) * 2) + 1;

	return -1;
}

double pleft = 0, pright = 0;
double _left = 0, _right = 0;
Filter f_fml(f_fmdeemp), f_fmr(f_fmdeemp);

uint16_t aout[512];
int aout_i = 0;
void ProcessAudioSample(float left, float right, double vel)
{
	float oleft = left, oright = right;

	double scale = ((vel - 1) * 0.5) + 1;

//	cerr << "A " << vel << ' ' << scale << ' ' << left - 2301136 << ' ' << right - 2812499 << ' '; 

	left *= scale;
	right *= scale;
	
	//cerr << left - 2301136 << ' ' << right - 2812499 << ' ' ; 
	cerr << "A " << left << ' ' << right << ' ' ; 

	if (!InRange(left, 2100000, 2500000)) left = pleft;
	cerr << left  ; 
	pleft = left;
	left -= 2301136;
	left *= (65535.0 / 300000.0);
	left = f_fml.feed(left);
	left += 32768;
	
	if (!InRange(right, 2601000, 3011200)) right = pright;
	cerr << ' ' << right << endl ; 
	pright = right;
	right -= 2812499;
	right *= (65535.0 / 300000.0);
	right = f_fmr.feed(right);
	right += 32768;

//	cerr << "A1 " << oleft << ' ' << left - _left << ' ' << oright << ' ' << right - _right << endl;
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

double cross = 0;

double line = -2;
int phase = -1;

int64_t vread = 0, aread = 0;
int va_ratio = 80;
	
double a_next = -1;
double afreq = 48000;
double agap  = dotclk / (double)va_ratio;

bool first = true;
double prev_linelen = ntsc_ipline;

int iline = 0;

double ProcessLine(uint16_t *buf, double begin, double end, int line)
{
	double tout[4096];
	double plevel1, pphase1;
	double plevel2, pphase2;
	double adjust1, adjust2, adjlen = ntsc_ipline;
	int oline = get_oline(line);

	double tgt_phase;

	Scale(buf, tout, begin, end, scale_tgt); 
	BurstDetect(tout, out_freq, 0, plevel1, pphase1); 
	BurstDetect(tout, out_freq, 228, plevel2, pphase2); 

	if (plevel1 < 1000) goto wrapup;
	if (plevel2 < 1000) goto wrapup;

	if (phase == -1) {
		phase = (fabs(pphase1) > (M_PIl / 2));
		iline = line;
		tgt_phase = ((line + phase + iline) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));
		cerr << "p " << pphase1 << ' ' << fabs(pphase1) << ' ' << phase << ' ' << tgt_phase << endl;
	} 

	tgt_phase = ((line + phase + iline) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));
	if (in_freq == 4) goto wrapup;

	adjlen = (end - begin) / (scale_tgt / ntsc_opline);
//	cerr << line << " " << 0 << ' ' << begin << ' ' << (begin + adjlen) << '/' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;

	for (int pass = 0; pass < ((in_freq == 4) ? 4 : 2); pass++) {
//	cerr << line << " 0" << ' ' << ((end - begin) / scale_tgt) * ntsc_ipline.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
		adjust1 = WrapAngle(tgt_phase - pphase1);	
		adjust2 = WrapAngle(pphase1 - pphase2);

		if (1 || in_freq != 4) {
			begin += (adjust1 * phasemult);
			end += ((adjust1 + adjust2) * phasemult);
		} else {
			if (pass == 0) begin += (adjust1 * (phasemult / 1.0));
			if (pass >= 1) end += (adjust2 * (phasemult / 2.0));
			//begin += (adjust1 * (phasemult / 2.0));
			//end += (adjust2 * (phasemult / 2.0));
		}

		Scale(buf, tout, begin, end, scale_tgt); 
		BurstDetect(tout, out_freq, 0, plevel1, pphase1); 
		BurstDetect(tout, out_freq, 228, plevel2, pphase2); 

		adjlen = (end - begin) / (scale_tgt / ntsc_opline);
					
		cerr << line << " " << pass << ' ' << begin << ' ' << (begin + adjlen) << '/' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
	}

wrapup:
	// LD only: need to adjust output value for velocity, and remove defects as possible
	double lvl_adjust = ((((end - begin) / iscale_tgt) - 1) * 2.0) + 1;
	int ldo = -128;
	for (int h = 0; (oline > 2) && (h < (211 * out_freq)); h++) {
		double v = tout[h + (int)(14 * out_freq)];
		double ire = in_to_ire(v);
		double o;

		if (in_freq != 4) {
			double freq = (ire * ((9300000 - 7600000) / 100)) + 7600000; 

//			cerr << h << ' ' << v << ' ' << ire << ' ' << freq << ' ';
			freq *= lvl_adjust;
//			cerr << freq << ' ';

			ire = ((freq - 7600000) / 1700000) * 100;
//			cerr << ire << endl;
			o = ire_to_out(ire);
		} else { 
			o = ire_to_out(in_to_ire(v));
		}

		if (despackle && (ire < -30) && (h > 80)) {
			if ((h - ldo) > 16) {
				for (int j = h - 4; j > 2 && j < h; j++) {
					double to = (frame[oline - 2][j - 2] + frame[oline - 2][j + 2]) / 2;
					frame[oline][j] = clamp(to, 0, 65535);
				}
			}
			ldo = h;
		}

		if (((h - ldo) < 16) && (h > 4)) {
			o = (frame[oline - 2][h - 2] + frame[oline - 2][h + 2]) / 2;
//			cerr << "R " << o << endl;
		}

		frame[oline][h] = clamp(o, 0, 65535);
	}
	
	frame[oline][0] = tgt_phase ? 32768 : 16384; 

	return begin + adjlen;
}

bool IsRegLine(double line)
{
	return ((line >= 11) && (line <= 262)) || ((line >= 273) && (line <= 524));
}

bool IsABlank(double line, double start, double len)
{
	bool isHalf = false;
	double end = start + len;

	double half = 227.5 * in_freq / 2;
	double full = 227.5 * in_freq;

	if ((line >= 520) || (line < 11) || ((line >= 260.0) && (line <= 273))) {
//		cerr << "halfline\n";
		isHalf = true;
	}

	if (end > full) return true;
	if (isHalf && (end > half)) return true;

//	cerr << "fail " << line << ' ' << end << " start " << start << " len " << len << " halfneed " << half << endl;

	return false;
}

int Process(uint16_t *buf, int len, float *abuf, int alen, int &aplen)
{
	double prevf, f = 0;
	double crosspoint = -1, prev_crosspoint = -1, tmp_crosspoint = -1;
	int prev_count = 0, count = 0, debounce = 0;
	int rv = 0;
	bool valid;

	double prev_linelen = ntsc_ipline;

	f_syncp.clear(ire_to_in(black_ire));

	cerr << "Process " << len << ' ' << (const void *)buf << endl;
	f_syncp.dump();

	int i;
	for (i = 0; (i >= 0) && (i < (len - 4096)); i++) {
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

			if ((debounce >= 16) && (count > (5 * in_freq))) crosspoint = tmp_crosspoint;

			if ((debounce >= 16) && (count > (5 * in_freq)) && prev_crosspoint > 0) {
				double begin = prev_crosspoint;
				double end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
				double linelen = crosspoint - prev_crosspoint; 
				
				int oline = get_oline(line + 0);
				
				valid = IsABlank(line, crosspoint - prev_crosspoint, count); 

				cerr << "S " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << ' ' << valid << endl;

				if (!valid) {
					cerr << "X " << line << ' ' << crosspoint - prev_crosspoint << ' ' << count << endl;

					crosspoint = bkup_crosspoint;
					debounce = 0;
					count = 0;
					continue;
				}
		
				double algap = fabs(linelen - prev_linelen);
				int acgap = abs(count - prev_count);	
				bool eed = false;

				cerr << "algap " << algap << " acgap " << acgap << endl; 
	
				//if (prev_count && (get_oline(line - 1) >= 0) && (get_oline(line) >= 0) && (get_oline(line + 1) >= 0) && (InRangeCF(algap, .5, 12.5) || InRangeCF(acgap, .8, 12.5))) {
				if (prev_count && IsRegLine(line) && (InRangeCF(algap, .5, 100) || InRangeCF(acgap, .8, 100))) {
					cerr << "E " << begin << ' ' << crosspoint << ' ' << end << ' ' << linelen << ' ' << prev_linelen << ' ' << prev_count << ' ' << count << endl;

					eed = true;

					cerr << linelen << ' ' << count - prev_count << endl;

#if 1
					if (InRangeCF(linelen + (count - prev_count), 227, 228)) {
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
						begin += (linelen + prev_linelen) / 1.0;
						prev_crosspoint += (linelen - prev_linelen) / 1.0;
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} 
#else
					if (InRangeCF(linelen, 140, 226.5)) {
						crosspoint += (in_freq * 227.5) - prev_linelen;
						
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					} else if (InRangeCF(linelen, 228.5, 280)) {
						crosspoint += (in_freq * 227.5) - prev_linelen;
						
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
					}
#endif
					cerr << "ES " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << endl;
				} else if (line > 0) {
					// special case for a bit of Airplane that had a dropout at the beginning of field

					// sync started early
					if (0 && InRangeCF(linelen, 140, 226)) {
						crosspoint += (in_freq * 227.5) - linelen;
						
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
						
						cerr << "Es " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << endl;
					}
#if 0
					if (!InRangeCF(linelen, 227.5 - 1, 227.5 + 1)) {
						if (linelen < (227 * in_freq)) {
							crosspoint += (227.5 * in_freq) - linelen;
						} else {
							prev_crosspoint -= (227.5 * in_freq) - linelen;
						}
						begin = prev_crosspoint;
						end = begin + ((crosspoint - prev_crosspoint) * scale_linelen);
						linelen = crosspoint - prev_crosspoint; 
						cerr << "Es " << line << ' ' << oline << ' ' << i << ' ' << crosspoint << ' ' << prev_crosspoint << ' ' << linelen << ' ' << count << endl;
					}	
#endif
				}

				prev_count = count;

				double adj_linelen = linelen;

//				cerr << line << ' ' << linelen << ' ' << ntsc_ipline * 0.9 << ' ' << count << ' ' << 11 * in_freq << endl;
				if ((line >= 0) && (linelen >= (ntsc_ipline * 0.9)) && (count > (14 * in_freq))) {
					// standard line
					int oline = get_oline(line);

					if (oline >= 0) {
						double adjend = ProcessLine(buf, begin, end, line); 

						adj_linelen = adjend - begin;
//						cerr << "ADJ " << end << ' ' << (adjend - begin) / 1820 << endl;	
					}	

					prev_linelen = linelen;					

					double tmplen = linelen;
					while (tmplen > (105 * in_freq)) {
						line = line + 0.5;
						tmplen -= ntsc_iphline;
					}
				} else if ((line == -1) && InRangeCF(linelen, 105, 120) && InRangeCF(count, 5, 20)) {
					line = 263.5;
					prev_linelen = ntsc_ipline;					
				} else if (((line == -1) || (line >= 525)) && (linelen > (225 * in_freq)) && InRangeCF(count, 5, 14)) {
					if (!first) {
						write(1, frame, sizeof(frame));
						memset(frame, 0, sizeof(frame));
					} else {
						first = false;
						phase = -1;
					}
					prev_linelen = ntsc_ipline;					
					line = 1;

//					if (still_handling) XXX
//					phase = -1;
					if (phase >= 0) phase = !phase;
				} else if ((line == -2) && (linelen > (in_freq * 220)) && (count > (10 * in_freq))) {
					line = -1;
				} else if (line >= 0) {
					double tmplen = linelen;
					while (tmplen > (105 * in_freq)) {
						line = line + 0.5;
						tmplen -= ntsc_iphline;
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
					double nomlen = InRangeCF(linelen, 105, 120) ? ntsc_iphline : ntsc_ipline;
					double scale = adj_linelen / nomlen;
					//double scale = linelen / nomlen;
					
					if (a_next < 0) a_next = prev_crosspoint / va_ratio;
						
//					cerr << "a " << scale << ' ' << lvl_adjust << ' ' << a_next * va_ratio << ' ' << crosspoint << endl; 
					while ((a_next * va_ratio) < crosspoint) {
						int index = (int)a_next * 2;

						float left = abuf[index], right = abuf[index + 1];
						
						ProcessAudioSample(left, right, scale);
	
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

	if (i < 0) cerr << "WTF\n";
	
	rv = prev_crosspoint - 200;

	a_next -= aplen;
	aplen *= 2;
	cerr << "N " << a_next << endl;
	vread += rv;

	return rv;
}

bool seven_five = (in_freq == 4);
double low = 65535, high = 0;

void autoset(uint16_t *buf, int len, bool fullagc = true)
{
	double f[len];
	int lowloc = -1;
	int checklen = (int)(in_freq * 4);

	if (!fullagc) {
		low = 65535;
		high = 0;
	}
	
	f_longsync.clear(0);

	// phase 1:  get low (-40ire) and high (??ire)
	for (int i = 0; i < len; i++) {
		f[i] = f_dsync.feed(buf[i]);

		if ((i > (in_freq * 256)) && (f[i] < low) && (f[i - checklen] < low)) {
			if (f[i - checklen] > f[i]) 
				low = f[i - checklen];
			else 
				low = f[i];

			lowloc = i;
		}
		
		if ((i > (in_freq * 256)) && (f[i] > high) && (f[i - checklen] > high)) {
			if (f[i - checklen] < f[i]) 
				high = f[i - checklen];
			else 
				high = f[i];
		}

//		cerr << i << ' ' << buf[i] << ' ' << f[i] << ' ' << low << ':' << high << endl;
	}

//	cerr << lowloc << ' ' << low << ':' << high << endl;

	// phase 2: attempt to figure out the 0IRE porch near the sync

	if (!fullagc) {
		int gap = high - low;
		int nloc;

		for (nloc = lowloc; (nloc > lowloc - (in_freq * 320)) && (f[nloc] < (low + (gap / 8))); nloc--);

		cerr << nloc << ' ' << (lowloc - nloc) / in_freq << ' ' << f[nloc] << endl;

		nloc -= (in_freq * 4);
		cerr << nloc << ' ' << (lowloc - nloc) / in_freq << ' ' << f[nloc] << endl;
	
		cerr << "old base:scale = " << inbase << ':' << inscale << endl;

		inscale = (f[nloc] - low) / ((seven_five) ? 47.5 : 40.0);
		inbase = low - (20 * inscale);	// -40IRE to -60IRE
		if (inbase < 1) inbase = 1;
		cerr << "new base:scale = " << inbase << ':' << inscale << endl;
	} else {
		inscale = (high - low) / 140.0;
	}

	inbase = low - (20 * inscale);	// -40IRE to -60IRE
	if (inbase < 1) inbase = 1;

	cerr << "new base:scale = " << inbase << ':' << inscale << endl;
	
	// rebase constants
	level_m40ire = ire_to_in(-40);
	level_0ire = ire_to_in(0);
	level_7_5_ire = ire_to_in(7.5);
	level_100ire = ire_to_in(100);
	level_120ire = ire_to_in(120);
	
	cross = ire_to_in(seven_five ? -5 : -20);
}

const int ablen = (5 * 1024);
const int vblen = ablen * 16;

const int absize = ablen * 8;
const int vbsize = vblen * 2;
	
float abuf[ablen * 2];
unsigned short inbuf[vblen];

int main(int argc, char *argv[])
{
	int rv = 0, arv = 0;
	bool do_autoset = (in_freq == 4);
	long long dlen = -1, tproc = 0;
	unsigned char *cinbuf = (unsigned char *)inbuf;
	unsigned char *cabuf = (unsigned char *)abuf;

	int c;

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	opterr = 0;
	
	while ((c = getopt(argc, argv, "hgs:n:i:a:Af")) != -1) {
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
			case 'g':
				do_autoset = !do_autoset;
				break;
			case 'n':
				despackle = false;
				break;
			case 'f':
				write_fields = true;
				break;
			case 'h':
				seven_five = true;
				break;
			default:
				return -1;
		} 
	} 

	cout << std::setprecision(8);

	cerr << "freq = " << in_freq << endl;

	rv = read(fd, inbuf, vbsize);
	while ((rv > 0) && (rv < vbsize)) {
		int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	cerr << "B" << absize << ' ' << ablen * 2 * sizeof(float) << endl ;

	if (afd != -1) {	
		arv = read(afd, abuf, absize);
		while ((arv > 0) && (arv < absize)) {
			int arv2 = read(afd, &cabuf[arv], absize - arv);
			if (arv2 <= 0) exit(0);
			arv += arv2;
		}
	}

	// base constant levels
	level_m40ire = ire_to_in(-40);
	level_0ire = ire_to_in(0);
	level_7_5_ire = ire_to_in(7.5);
	level_100ire = ire_to_in(100);
	level_120ire = ire_to_in(120);

	cross = ire_to_in(seven_five ? -5 : -20);

	int aplen = 0;
	while (rv == vbsize && ((tproc < dlen) || (dlen < 0))) {
		if (do_autoset) {
			autoset(inbuf, vbsize / 2);
		}
/*
		for (int i = 0; i < (arv / 8); i+=2) {
			cerr << i << ' ' << abuf[i] << ' ' << abuf[i + 1] << endl;
		}
*/
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
//			cerr << "AX " << absize << ' ' << aplen * 4 << ' ' << (double)(absize - (aplen * 4)) << ' ' << abuf[0] << ' ' ;
			memmove(abuf, &abuf[aplen], absize - (aplen * 4));
			cerr << abuf[0] << endl;

			arv = (absize - (aplen * 4));
//                	arv = read(afd, &abuf[ablen - aplen], aplen * 4) + (absize - (aplen * 4));
			while (arv < absize) {
//				usleep(100000);
				int arv2 = read(afd, &cabuf[arv], absize - arv);
				if (arv2 <= 0) exit(0);
				arv += arv2;
			}

			if (arv == 0) exit(0);
		}
	}

	return 0;
}
