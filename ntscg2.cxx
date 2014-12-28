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
const double ntsc_ipline = 227.5 * in_freq; // pixels per line
const double ntsc_opline = 227.5 * out_freq; // pixels per line
//const int ntsc_oplinei = 227.5 * out_freq; // pixels per line

const double ntsc_blanklen = 9.2;

// we want the *next* colorburst as well for computation 
const double scale_linelen = ((63.5 + ntsc_blanklen) / 63.5); 

const double ntsc_ihsynctoline = ntsc_ipline * (ntsc_blanklen / 63.5);
const double iscale_tgt = ntsc_ipline + ntsc_ihsynctoline;

const double ntsc_hsynctoline = ntsc_opline * (ntsc_blanklen / 63.5);
const double scale_tgt = ntsc_opline + ntsc_hsynctoline;

const double phasemult = 1.591549430918953e-01 * in_freq; // * 0.99999;

double hfreq = 525.0 * (30000.0 / 1001.0);

long long fr_count = 0, au_count = 0;

int writeonfield = 1;

bool audio_only = false;

double inbase = 1;	// IRE == -60
double inscale = 327.68;

long long a_read = 0, v_read = 0;
int va_ratio = 80;

const int vblen = (1820 * 1100);	// should be divisible evenly by 16
const int ablen = (1820 * 1100) / 40;

const int absize = ablen * 8;
const int vbsize = vblen * 2;
	
float abuf[ablen * 2];
unsigned short inbuf[vblen];

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
                
bool InRange(double v, double l, double h) {
	return ((v > l) && (v < h));
}

bool InRangeCF(double v, double l, double h) {
	l *= in_freq;
	h *= in_freq;
	return ((v > l) && (v < h));
}

// tunables

bool freeze_frame = false;
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

		// XXX: use ire->int here
		if (x < 6000) x = 6000;
		if (x >= 26000) x = 26000;

		double v = f_bpcolor->feed(x);

		double q = f_syncr.feed(v * _cos[l % freq]);
		double i = f_synci.feed(-v * _sin[l % freq]);

		double level = ctor(i, q);

		if (((l - loc) > 16) && (level > plevel) && (level < 10000)) {
			ploc = l;
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
	else if (l < 263) return (l - 10) * 2;
	else if (l < 273) return -1;
	else if (l < 525) return ((l - 273) * 2) + 1;

	return -1;
}

double pleft = 0, pright = 0;
double _left = 0, _right = 0;
Filter f_fml(f_fmdeemp), f_fmr(f_fmdeemp);

uint16_t aout[512];
int aout_i = 0;
void ProcessAudioSample(float left, float right, double vel)
{
//	double scale = ((vel - 1) * 0.5) + 1;

	left *= (65535.0 / 300000.0);
	left = f_fml.feed(left);
	left += 32768;
	
	right *= (65535.0 / 300000.0);
	right = f_fmr.feed(right);
	right += 32768;

	_left = left;
	_right = right;

	aout[aout_i * 2] = clamp(left, 0, 65535);
	aout[(aout_i * 2) + 1] = clamp(right, 0, 65535);
	
	aout_i++;
	if (aout_i == 256) {
		int rv = write(audio_only ? 1 : 3, aout, sizeof(aout));

		rv = aout_i = 0;
	}
}

double afreq = 48000;

double prev_time = -1;
double next_audsample = 0;
size_t prev_loc = -1;

long long prev_index = 0, prev_i = 0;
void ProcessAudio(double frame, long long loc, float *abuf)
{
	double time = frame / (30000.0 / 1001.0);

	if (afd < 0) return;

	if (prev_time >= 0) {
		while (next_audsample < time) {
			double i1 = (next_audsample - prev_time) / (time - prev_time); 
			long long i = (i1 * (loc - prev_loc)) + prev_loc;

			if (i < v_read) {
				ProcessAudioSample(f_fml.val(), f_fmr.val(), 1.0);  
			} else {
				long long index = (i / va_ratio) - a_read;
				if (index >= ablen) {
					cerr << "audio error " << frame << " " << time << " " << i1 << " " << i << " " << index << " " << ablen << endl;
					index = ablen - 1;
//					exit(0);
				} 
				float left = abuf[index * 2], right = abuf[(index * 2) + 1];
				cerr << "A " << frame << ' ' << loc << ' ' << i1 << ' ' << i << ' ' << i - prev_i << ' ' << index << ' ' << index - prev_index << ' ' << left << ' ' << right << endl;
				prev_index = index;
				prev_i = i;
				ProcessAudioSample(left, right, 1.0);
			} 

			next_audsample += 1.0 / afreq;
		}
	}

	prev_time = time; prev_loc = loc;
}

double cross = 0;

double tline = 0, line = -2;
int phase = -1;

bool first = true;
double prev_linelen = ntsc_ipline;
double prev_offset = 0.0;

double prev_begin = 0;

int iline = 0;
int frameno = -1;

double ProcessLine(uint16_t *buf, double begin, double end, int line, bool err = false)
{
	double tout[8192];
	double plevel1, pphase1;
	double plevel2, pphase2;
	double adjust1, adjust2, adjlen = ntsc_ipline;
	int pass = 0;

	double orig_begin = begin;

	int oline = get_oline(line);

	if (oline < 0) return 0;

	double tgt_phase;

	Scale(buf, tout, begin, end, scale_tgt); 
	BurstDetect(tout, out_freq, 0, plevel1, pphase1); 
	BurstDetect(tout, out_freq, 228, plevel2, pphase2); 

	cerr << "levels " << plevel1 << ' ' << plevel2 << endl;

	if ((plevel1 < 2000) || (plevel2 < 1000)) {
		begin += prev_offset;
		end += prev_offset;
	
		Scale(buf, tout, begin, end, scale_tgt); 
		goto wrapup;
	}

	if (err) {
		begin += prev_offset;
		end += prev_offset;
	}

	if (phase == -1) {
		phase = (fabs(pphase1) > (M_PIl / 2));
		iline = line;
		tgt_phase = ((line + phase + iline) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));
		cerr << "p " << pphase1 << ' ' << fabs(pphase1) << ' ' << phase << ' ' << tgt_phase << endl;
	} 

	tgt_phase = ((line + phase + iline) % 2) ? (-180 * (M_PIl / 180.0)) : (0 * (M_PIl / 180.0));
	if (in_freq == 4) goto wrapup;

	adjlen = (end - begin) / (scale_tgt / ntsc_opline);
	cerr << line << " " << oline << " " << 0 << ' ' << begin << ' ' << (begin + adjlen) << '/' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;

	for (pass = 0; pass < ((in_freq == 4) ? 4 : 2); pass++) {
//		cerr << line << " 0" << ' ' << ((end - begin) / scale_tgt) * ntsc_ipline.0 << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
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
		double v = tout[h + (int)(15 * out_freq)];
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
		//if (!(oline % 2)) frame[oline][h] = clamp(o, 0, 65535);
	}
/*
        if (bad) {
                frame[oline][2] = 48000;
                frame[oline][3] = 48000;
                frame[oline][4] = 48000;
                frame[oline][5] = 48000;
        }
*/
        if (!pass) {
                frame[oline][2] = 32000;
                frame[oline][3] = 32000;
                frame[oline][4] = 32000;
                frame[oline][5] = 32000;
		cerr << "BURST ERROR " << line << " " << pass << ' ' << begin << ' ' << (begin + adjlen) << '/' << end  << ' ' << plevel1 << ' ' << pphase1 << ' ' << pphase2 << endl;
        } else {
		prev_offset = begin - orig_begin;
	}

	cerr << "GAP " << begin - prev_begin << endl;
	
	frame[oline][0] = tgt_phase ? 32768 : 16384; 
	frame[oline][1] = plevel1; 

	prev_begin = begin;

	return adjlen;
}

double psync[1820*1200];
int Process(uint16_t *buf, int len, float *abuf, int alen)
{
	bool first = true;

	f_syncid.clear(0);

	cerr << "len " << len << endl;
	for (int i = 0; i < len; i++) {
		double val = f_syncid.feed(buf[i] && (buf[i] < 12000)); 
		if (i > syncid_offset) psync[i - syncid_offset] = val; 
	}

	long long syncstart = -1;
	int prevsync = -1;
	int insync = 0;
	double line = 0;

	double prev_begin = 0, prev_end = 0, prev_linelen = ntsc_ipline;
	double begin = -1, end = -1, linelen = ntsc_ipline;

	int i, prev = 0;
	for (i = 500; i < len - syncid_offset; i++) {
		double level = psync[i];

		// look for peaks with valid level values
		if ((level > .08) && (level > psync [i - 1]) && (level > psync [i + 1])) {
			bool canstartsync = true;
			bool probsync = false;
	
			if (!first && !(InRange(line, 261, 265) || InRange(line, 520, 530))) canstartsync = false;	

			probsync = insync && InRangeCF(i - syncstart, 0, 8.9 * 227.5);

			cerr << i << ' ' << i - prev << ' ' << line << ' ' << buf[i] << ' ' << psync[i] << ' ' << canstartsync << ' ' << probsync << endl;

			if ((canstartsync && InRange(level, 0.13, 0.20)) || (probsync && InRange(level, 0.20, 0.25))) {
				if (!insync) {
					syncstart = i;

					insync = ((i - prev) < (150 * in_freq)) ? 2 : 1;
					cerr << frameno << " sync type " << insync << endl;

					if (insync == writeonfield) {
						if (!first) {
							frameno++;
							write(1, frame, sizeof(frame));
							memset(frame, 0, sizeof(frame));
							return i - 32768;
						} else {
							first = false;
							//ProcessAudio(frameno, v_read + i, abuf);
						}
						if (!freeze_frame && phase >= 0) phase = !phase;
					} else {
//						if (!first) ProcessAudio(frameno + .5, v_read + i, abuf);
					}

					prev_offset = 0;
				}
			} else if (InRange(level, 0.25, 0.6) || (!insync && InRange(level, 0.14, 0.25))) {
				bool bad = false;
				bool outofsync = false;

				prev_begin = begin;
				prev_end = end;
				prev_linelen = linelen;

				begin = -1; end = -1;

				if (insync) {
					line = (insync == 2) ? 273 : 10;
					prevsync = insync;
					insync = 0;
					outofsync = true;
				} else {
					line++;
				}

				if (!insync) { 
					for (int x = i; begin == -1 && x > (i - 100); x--) {
						if (buf[x] > 12000) begin = x; 
					}
					
					for (int x = i; end == -1 && x < (i + 100); x++) {
						if (buf[x] > 12000) end = x; 
					}

					bad = (begin < 0) || (end < 0) || (!outofsync && (!InRange(end - begin, 128, 139)));
				//	bad = (begin < 0) || (end < 0) || (!outofsync && (!InRange(end - begin, 128, 136) || !InRangeCF(i - prev, 226.5, 228.5)));
					cerr << line << ' ' << bad << ' ' << prev_begin << ' ' << begin << ' ' << end << ' ' << end - begin << ' ' << scale_tgt << endl;
				}
				// normal line
				if (bad || buf[i] > 12000) {
					// defective line
					begin = prev_begin + prev_linelen;
					end = prev_end + prev_linelen;
					cerr << "BAD " << bad << ' ' << begin << ' ' << end << endl;
				}

				linelen = end - prev_end;

				double send = prev_begin + ((begin - prev_begin) * scale_linelen);

				if (!first) {
					linelen = ProcessLine(buf, prev_begin, send, line, bad); 
					ProcessAudio((line / 525.0) + frameno, v_read + begin, abuf); 
				}
			} else if (level > 1.0) {
				// in vsync/equalizing lines - don't care right now
				if (!insync) {
					cerr << "belated sync detect\n";
					insync = (prevsync == 1) ? 2 : 1;
					if ((insync == 1) && !freeze_frame && phase >= 0) phase = !phase;
				}
			}  
			prev = i;
		}
	}	

	return (i > 16384) ? i - 16384 : 0;
}

bool seven_five = (in_freq == 4);
double low = 65535, high = 0;

double f[vblen];

void autoset(uint16_t *buf, int len, bool fullagc = true)
{
	int lowloc = -1;
	int checklen = (int)(in_freq * 4);

	if (!fullagc) {
		low = 65535;
		high = 0;
	}
	
//	f_longsync.clear(0);

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
	
	cross = ire_to_in(seven_five ? -5 : -20);
}

int main(int argc, char *argv[])
{
	int rv = 0, arv = 0;
	bool do_autoset = (in_freq == 4);
	long long dlen = -1;
	unsigned char *cinbuf = (unsigned char *)inbuf;
	unsigned char *cabuf = (unsigned char *)abuf;

	int c;

	cerr << std::setprecision(10);

	opterr = 0;
	
	while ((c = getopt(argc, argv, "mhgs:n:i:a:Af")) != -1) {
		switch (c) {
			case 'm':	// "magnetic video" mode - bottom field first
				writeonfield = 2;
				break;
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
				freeze_frame = true;
				break;
			case 'h':
				seven_five = true;
				break;
			default:
				return -1;
		} 
	} 

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
							
	memset(frame, 0, sizeof(frame));

	cross = ire_to_in(seven_five ? -5 : -20);

	f_linelen.clear(1820);

	size_t aplen = 0;
	while (rv == vbsize && ((v_read < dlen) || (dlen < 0))) {
		if (do_autoset) {
			autoset(inbuf, vbsize / 2);
		}

		int plen = Process(inbuf, rv / 2, abuf, arv / 8);
		
		if (plen < 0) {
			cerr << "skipping ahead" << endl;
			plen = vblen / 2;
		}

		v_read += plen;
		aplen = (v_read / va_ratio) - a_read;

		a_read += aplen;

//		cerr << "move " << plen << ' ' << (vblen - plen) * 2; 
		memmove(inbuf, &inbuf[plen], (vblen - plen) * 2);
	
                rv = read(fd, &inbuf[(vblen - plen)], plen * 2) + ((vblen - plen) * 2);
		while ((rv > 0) && (rv < vbsize)) {
			int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}	
		
		if (afd != -1) {	
//			cerr << "AX " << absize << ' ' << aplen * 4 << ' ' << (double)(absize - (aplen * 4)) << ' ' << abuf[0] << ' ' ;
			cerr << "AA " << plen << ' ' << aplen << ' ' << v_read << ' ' << a_read << ' ' << (double)v_read / (double)a_read << endl;
			memmove(abuf, &abuf[aplen * 2], absize - (aplen * 8));
			cerr << abuf[0] << endl;

			arv = (absize - (aplen * 8));
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
