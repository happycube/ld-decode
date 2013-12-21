/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <list>
#include <queue>
#include <complex>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// capture frequency and fundamental NTSC color frequency
//const double CHZ = (1000000.0*(315.0/88.0)*8.0);
//const double FSC = (1000000.0*(315.0/88.0));

using namespace std;

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}

inline double dftc(double *buf, int offset, int len, double bin, double &fc, double &fci) 
{
	fc = 0.0; fci = 0.0;

	for (int k = (-len + 1); k < len; k++) {
//		cout << offset + k << ' ' << len << endl;
		double o = buf[offset + k]; 
		
		fc += (o * cos((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
		fci -= (o * sin((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
	}

	return ctor(fc, fci);
}

inline double dft(double *buf, int offset, int len, double bin) 
{
	double fc, fci;

	dftc(buf, offset, len, bin, fc, fci);

	return ctor(fc, fci);
}

inline double addmul16(double *b, double *x)
{
	double y[4];

	// this *was* an attempt to force 256-bit ops, but it still made things
	// a little faster - latency fix?
	y[0] = b[0] * x[0];
	y[1] = b[1] * x[1];
	y[2] = b[2] * x[2];
	y[3] = b[3] * x[3];
	y[0] += b[4] * x[4];
	y[1] += b[5] * x[5];
	y[2] += b[6] * x[6];
	y[3] += b[7] * x[7];
	y[0] += b[8] * x[8];
	y[1] += b[9] * x[9];
	y[2] += b[10] * x[10];
	y[3] += b[11] * x[11];
	y[0] += b[12] * x[12];
	y[1] += b[13] * x[13];
	y[2] += b[14] * x[14];
	y[3] += b[15] * x[15];

	return (y[0] + y[1] + y[2] + y[3]);
}

class Filter {
	protected:
		int order;
		bool isIIR;
		vector<double> a, b;
		vector<double> y, x;
	public:
		Filter(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			if (_a) {
				a.insert(b.begin(), _a, _a + order);
				isIIR = true;
			} else {
				a.push_back(1.0);
				isIIR = false;
			}
			b.insert(b.begin(), _b, _b + order);
			x.resize(order);
			y.resize(order);
	
			clear();
		}

		Filter(Filter *orig) {
			order = orig->order;
			isIIR = orig->isIIR;
			a = orig->a;
			b = orig->b;
			x.resize(order);
			y.resize(order);
				
			clear();
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = val;
			}
		}

		inline double feed(double val) {
			double a0 = a[0];
			double y0;

			double *x_data = x.data();
			double *y_data = y.data();

			memmove(&x_data[1], x_data, sizeof(double) * (order - 1)); 
			if (isIIR) memmove(&y_data[1], y_data, sizeof(double) * (order - 1)); 

			x[0] = val;
			y0 = 0; // ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			if (isIIR) {
				for (int o = 0; o < order; o++) {
					y0 += ((b[o] / a0) * x[o]);
					if (o) y0 -= ((a[o] / a0) * y[o]);
					//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
				}
			} else {
				int o = 0;

				for (o = 0; (o + 16) < order; o+=16) {
					y0 += addmul16(&b[o], &x[o]);
				}

				for (; o < order; o++) {
					y0 += b[o] * x[o];
				}
			}

			y[0] = y0;
			return y[0];
		}
		double val() {return y[0];}
};

//const double f35_1_3mhz_b37[] {-1.234967629730642e-03, -1.185466683134518e-03, -1.168034466004734e-03, -1.018179088134394e-03, -5.140864556073300e-04, 5.984847487321350e-04, 2.573596558144000e-03, 5.628653493395202e-03, 9.908630728154117e-03, 1.545574882129113e-02, 2.218888007617535e-02, 2.989593966974851e-02, 3.824102397754865e-02, 4.678629045338454e-02, 5.502674991770788e-02, 6.243449677938711e-02, 6.850765013626178e-02, 7.281858582758209e-02, 7.505600313509912e-02, 7.505600313509912e-02, 7.281858582758211e-02, 6.850765013626180e-02, 6.243449677938712e-02, 5.502674991770790e-02, 4.678629045338454e-02, 3.824102397754866e-02, 2.989593966974851e-02, 2.218888007617536e-02, 1.545574882129114e-02, 9.908630728154115e-03, 5.628653493395204e-03, 2.573596558144003e-03, 5.984847487321354e-04, -5.140864556073300e-04, -1.018179088134393e-03, -1.168034466004735e-03, -1.185466683134518e-03, -1.234967629730642e-03};
//const double f35_1_3mhz_b37[] {-7.908471351578800e-05, 2.277934696402544e-04, 7.019529636956475e-04, 1.506640429670915e-03, 2.806384564097780e-03, 4.749348500734396e-03, 7.449923331314437e-03, 1.097327749610654e-02, 1.532345418455140e-02, 2.043632667545368e-02, 2.617830374691917e-02, 3.235116187465518e-02, 3.870281626406508e-02, 4.494328286369096e-02, 5.076458278771162e-02, 5.586294838455438e-02, 5.996144586256753e-02, 6.283105823829103e-02, 6.430838307579578e-02, 6.430838307579580e-02, 6.283105823829103e-02, 5.996144586256753e-02, 5.586294838455438e-02, 5.076458278771161e-02, 4.494328286369095e-02, 3.870281626406508e-02, 3.235116187465517e-02, 2.617830374691918e-02, 2.043632667545368e-02, 1.532345418455140e-02, 1.097327749610655e-02, 7.449923331314445e-03, 4.749348500734398e-03, 2.806384564097780e-03, 1.506640429670914e-03, 7.019529636956480e-04, 2.277934696402545e-04, -7.908471351578800e-05};

const double f35_1_3mhz_b37[] {2.200155034713029e-03, 2.590600183023168e-03, 3.430179677505190e-03, 4.787695086285943e-03, 6.708040380703718e-03, 9.208077736016815e-03, 1.227396632892245e-02, 1.586014554001170e-02, 1.989007976379836e-02, 2.425876958327282e-02, 2.883692957135977e-02, 3.347663283240412e-02, 3.801813278827727e-02, 4.229749925011277e-02, 4.615465315333738e-02, 4.944135587700042e-02, 5.202870675354425e-02, 5.381372653556364e-02, 5.472465392414715e-02, 5.472465392414715e-02, 5.381372653556363e-02, 5.202870675354426e-02, 4.944135587700043e-02, 4.615465315333738e-02, 4.229749925011277e-02, 3.801813278827728e-02, 3.347663283240412e-02, 2.883692957135978e-02, 2.425876958327282e-02, 1.989007976379836e-02, 1.586014554001171e-02, 1.227396632892246e-02, 9.208077736016819e-03, 6.708040380703718e-03, 4.787695086285940e-03, 3.430179677505191e-03, 2.590600183023169e-03, 2.200155034713029e-03};

const double f35_1_3_b74[] {6.095948796663983e-04, 6.969062947302427e-04, 7.846197019254240e-04, 8.671281722787260e-04, 9.306332906966004e-04, 9.534688608486608e-04, 9.076430961685578e-04, 7.615620828775578e-04, 4.837711833807570e-04, 4.743269035668027e-05, -5.648411336582202e-04, -1.356250336989300e-03, -2.311648160381151e-03, -3.394434180883840e-03, -4.544920181177649e-03, -5.680494830327633e-03, -6.697783812723640e-03, -7.476846928359610e-03, -7.887284916380240e-03, -7.795959985152708e-03, -7.075879466624239e-03, -5.615665202905854e-03, -3.328943959261050e-03, -1.629552286149473e-04, 3.894312539079137e-03, 8.809076982116285e-03, 1.449930738440235e-02, 2.083519596719662e-02, 2.764269392599351e-02, 3.471003704706929e-02, 4.179696961214230e-02, 4.864617376506342e-02, 5.499624031997632e-02, 6.059538981775844e-02, 6.521507997923769e-02, 6.866262398549862e-02, 7.079199503902095e-02, 7.151210341191104e-02, 7.079199503902096e-02, 6.866262398549862e-02, 6.521507997923769e-02, 6.059538981775844e-02, 5.499624031997633e-02, 4.864617376506342e-02, 4.179696961214231e-02, 3.471003704706927e-02, 2.764269392599351e-02, 2.083519596719662e-02, 1.449930738440235e-02, 8.809076982116288e-03, 3.894312539079138e-03, -1.629552286149476e-04, -3.328943959261050e-03, -5.615665202905853e-03, -7.075879466624240e-03, -7.795959985152710e-03, -7.887284916380240e-03, -7.476846928359615e-03, -6.697783812723640e-03, -5.680494830327637e-03, -4.544920181177650e-03, -3.394434180883839e-03, -2.311648160381153e-03, -1.356250336989300e-03, -5.648411336582202e-04, 4.743269035668022e-05, 4.837711833807570e-04, 7.615620828775592e-04, 9.076430961685571e-04, 9.534688608486612e-04, 9.306332906966010e-04, 8.671281722787257e-04, 7.846197019254246e-04, 6.969062947302430e-04, 6.095948796663983e-04};

const double f35_1_3_b75[] {5.628725214782298e-04, 6.629008867452294e-04, 7.649194860782425e-04, 8.650010911901207e-04, 9.513153600016910e-04, 1.004090257971544e-03, 9.967418786062173e-04, 8.981783944188360e-04, 6.761622139438639e-04, 3.014961316868030e-04, -2.473045064800951e-04, -9.792705320984063e-04, -1.886631074489099e-03, -2.941327912715128e-03, -4.092825317222753e-03, -5.267572021517578e-03, -6.370358813955671e-03, -7.287673409586681e-03, -7.892994392968856e-03, -8.053800728391684e-03, -7.639916193176058e-03, -6.532672531913339e-03, -4.634273301669063e-03, -1.876682091940293e-03, 1.770649348640858e-03, 6.294852825960217e-03, 1.163605885424649e-02, 1.768655689799217e-02, 2.429292403709345e-02, 3.126114330780121e-02, 3.836452191389125e-02, 4.535401532482878e-02, 5.197038165322374e-02, 5.795744587189171e-02, 6.307565704622189e-02, 6.711508193322417e-02, 6.990699892180458e-02, 7.133333666918365e-02, 7.133333666918365e-02, 6.990699892180459e-02, 6.711508193322419e-02, 6.307565704622191e-02, 5.795744587189171e-02, 5.197038165322375e-02, 4.535401532482879e-02, 3.836452191389126e-02, 3.126114330780122e-02, 2.429292403709345e-02, 1.768655689799217e-02, 1.163605885424649e-02, 6.294852825960215e-03, 1.770649348640859e-03, -1.876682091940294e-03, -4.634273301669064e-03, -6.532672531913338e-03, -7.639916193176058e-03, -8.053800728391682e-03, -7.892994392968859e-03, -7.287673409586685e-03, -6.370358813955676e-03, -5.267572021517580e-03, -4.092825317222753e-03, -2.941327912715128e-03, -1.886631074489098e-03, -9.792705320984070e-04, -2.473045064800954e-04, 3.014961316868029e-04, 6.761622139438646e-04, 8.981783944188359e-04, 9.967418786062173e-04, 1.004090257971545e-03, 9.513153600016908e-04, 8.650010911901212e-04, 7.649194860782425e-04, 6.629008867452298e-04, 5.628725214782296e-04};

const double f35_0_6mhz_b81[] {-5.557093857983986e-04, -5.386061875052753e-04, -5.304121793359423e-04, -5.263776829954182e-04, -5.203068760237518e-04, -5.046571743032663e-04, -4.706854629670484e-04, -4.086385760416698e-04, -3.079841041580603e-04, -1.576763716088336e-04, 5.354869496762519e-05, 3.368570506749334e-04, 7.029863985426006e-04, 1.161911045570856e-03, 1.722510709077681e-03, 2.392252347477940e-03, 3.176893957593510e-03, 4.080218902859782e-03, 5.103808720191829e-03, 6.246861511330179e-03, 7.506061977108642e-03, 8.875507926065949e-03, 1.034669671316860e-02, 1.190857357553547e-02, 1.354764226882133e-02, 1.524813681159704e-02, 1.699225155821051e-02, 1.876042528588617e-02, 2.053167354082170e-02, 2.228396218014330e-02, 2.399461390784434e-02, 2.564073866497750e-02, 2.719967802389246e-02, 2.864945327371738e-02, 2.996920668350137e-02, 3.113962549740770e-02, 3.214333855280412e-02, 3.296527600953923e-02, 3.359298352257743e-02, 3.401688325927180e-02, 3.423047542955864e-02, 3.423047542955864e-02, 3.401688325927180e-02, 3.359298352257743e-02, 3.296527600953923e-02, 3.214333855280413e-02, 3.113962549740771e-02, 2.996920668350136e-02, 2.864945327371738e-02, 2.719967802389247e-02, 2.564073866497751e-02, 2.399461390784434e-02, 2.228396218014329e-02, 2.053167354082171e-02, 1.876042528588618e-02, 1.699225155821050e-02, 1.524813681159704e-02, 1.354764226882133e-02, 1.190857357553548e-02, 1.034669671316860e-02, 8.875507926065951e-03, 7.506061977108645e-03, 6.246861511330181e-03, 5.103808720191825e-03, 4.080218902859783e-03, 3.176893957593512e-03, 2.392252347477942e-03, 1.722510709077683e-03, 1.161911045570855e-03, 7.029863985426009e-04, 3.368570506749333e-04, 5.354869496762523e-05, -1.576763716088337e-04, -3.079841041580605e-04, -4.086385760416702e-04, -4.706854629670486e-04, -5.046571743032660e-04, -5.203068760237521e-04, -5.263776829954183e-04, -5.304121793359425e-04, -5.386061875052753e-04, -5.557093857983986e-04};

// fir1(15, (4.0/freq), 'hamming');
const double f_lpf40_15_hamming_b[] {-2.946846406369798e-03, -5.818304239908221e-03, -8.744902449172498e-03, -1.174167602472263e-04, 3.446404677343186e-02, 9.712591957457362e-02, 1.688365234767659e-01, 2.172009800309264e-01, 2.172009800309265e-01, 1.688365234767659e-01, 9.712591957457366e-02, 3.446404677343189e-02, -1.174167602472263e-04, -8.744902449172497e-03, -5.818304239908217e-03, -2.946846406369798e-03};


const double f_hsync8[] {1.447786467971050e-02, 4.395811440315845e-02, 1.202636955256379e-01, 2.024216184054497e-01, 2.377574139720867e-01, 2.024216184054497e-01, 1.202636955256379e-01, 4.395811440315847e-02, 1.447786467971050e-02};

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 300000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

struct YIQ {
	double y, i, q;

	YIQ(double _y = 0.0, double _i = 0.0, double _q = 0.0) {
		y = _y; i = _i; q = _q;
	};
};

double clamp(double v, double low, double high)
{
	if (v < low) return low;
	else if (v > high) return high;
	else return v;
}

struct RGB {
	double r, g, b;

	void conv(YIQ y) { 
	//	y.i = clamp(y.i, -0.5957, .5957);
	//	y.q = clamp(y.q, -0.5226, .5226);

		y.y -= (.4 / 1.4);
		y.y *= 1.4; 
		y.y = clamp(y.y, 0, 1.0);

		r = (y.y * 1.164) + (1.596 * y.i);
		g = (y.y * 1.164) - (0.813 * y.i) - (y.q * 0.391);
		b = (y.y * 1.164) + (y.q * 2.018);

		r = clamp(r, 0, 1.05);
		g = clamp(g, 0, 1.05);
		b = clamp(b, 0, 1.05);
		//cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
		//cerr << 'r' << r << " g" << g << " b" << b << endl;
	};
};

// NewCode

/* 
 * NTSC(/PAL) Description 
 * ----------------
 *
 * There are a few different types of NTSC lines with different contained data.  While PAL is similar, I 
 * am currently only concerned with NTSC.  Perhaps I will wind up with PAL video tapes someday... 
 *
 * Since many of these lines are repeated, we will describe these lines and then generate the typical frame.
 */

// These are bit fields, since data type can be added to a core type
enum LineFeatures {
	// Core line types
	LINE_NORMAL       = 0x01, /* standard line - Porch, sync pulse, porch, color burst, porch, data */ 
	LINE_EQUALIZATION = 0x02, /* -SYNC, half line, -SYNC, half line */ 
	LINE_FIELDSYNC    = 0x04, /* Long -SYNC, serration pulse std sync pulse len */ 
	LINE_HALF         = 0x08, /* Half-length video line at end of odd field, followed by -SYNC at 262.5 */ 
	// Line data features
	LINE_VIDEO	  = 0x0040, /* What we actually care about - picture data! */
	LINE_MULTIBURST   = 0x0080, /* White, 0.5-4.1mhz burst pulses */
	LINE_COMPTEST     = 0x0100, /* 3.58mhz bursts, short pulses, white */
	LINE_REFSIGNAL    = 0x0200, /* Burst, grey, black */
	LINE_MCA	  = 0x0400, /* LD-specific MCA code (only matters on GM disks) */
	LINE_PHILLIPS	  = 0x0800, /* LD-specific 48-bit Phillips code */
	LINE_CAPTION	  = 0x1000, /* Closed captioning */
	LINE_WHITEFLAG	  = 0x2000, /* CAV LD only - depicts beginning of new film frame */
};

int NTSCLine[526], NTSCLineLoc[526];

// WIP
void buildNTSCLines()
{
	int i;

	for (i = 0; i < 526; i++) NTSCLineLoc[i] = -1;

	// Each line array starts with 1 to line up with documetnation 

	// Odd field is line 1-263, even field is 264-525 

	// first set of eq lines
	for (i = 1; i <= 3; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_EQUALIZATION; 

	for (i = 4; i <= 6; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_FIELDSYNC; 

	for (i = 7; i <= 9; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_EQUALIZATION; 

	// While lines 10-21 have regular sync, but they contain special non-picture information 	
	for (i = 10; i <= 21; i++) NTSCLine[i] = NTSCLine[264 + i] = LINE_NORMAL; 

	// define odd field
	NTSCLine[10] |= LINE_WHITEFLAG; 
	NTSCLine[18] |= LINE_PHILLIPS; 

	for (i = 22; i <= 263; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 22) * 2) + 0;
	}
	NTSCLine[263] = LINE_HALF | LINE_VIDEO;

	// define even field
	NTSCLine[273] |= LINE_WHITEFLAG; 
	NTSCLine[264 + 18] |= LINE_PHILLIPS; 
	
	for (i = 285; i <= 525; i++) {
		NTSCLine[i] = LINE_NORMAL | LINE_VIDEO; 
		NTSCLineLoc[i] = ((i - 285) * 2) + 1;
	}
}

enum tbc_type {TBC_HSYNC, TBC_CBURST};

class NTSColor {
	protected:
		Filter *f_i, *f_q;
		Filter *f_synci, *f_syncq;
		Filter *f_post;

		Filter *f_linelen;

		double fc, fci;
		int freq;

		tbc_type tbc;

		int cline;

		int fieldcount;

		int counter, lastline, lastsync;
		bool insync;
		double peaksync, peaksynci, peaksyncq;

		double _sin[32], _cos[32];
		double _sinp[32], _cosp[32];

		vector<double> prev, buf_1h;
		double circbuf[22];

		double phase, level;
		int phase_count;
		bool phased;

		double adjfreq;

		double poffset, pix_poffset;

		vector<double> line;
	
		YIQ frame[2000 * 1024];
		
		vector<YIQ> *buf;

		int prev_igap, igap;
	public:
		bool get_newphase(double &afreq, double &np) {
			if (phased) {
				afreq = adjfreq;
				np = phase;
				phased = false;
				return true;
			} else return false;
		}	

		void set_tbc(tbc_type type) {
			tbc = type;
		}

		bool whiteflag_decode() {
			int oc = 0;

			for (double c: line) {
				if (c > 0.5) {
					oc++;
				}
				if (oc > 700) return true;
			}
//			cerr << "W" << oc << endl;
			return false;
		}

		unsigned long phillips_decode() {
			int i = 0;
			int oc = 0;
			int lastone = 275 - 68 - 0;

			unsigned long code = 0;

			for (double c: line) {
				if (c > 0.8) {
					oc++;
				} else {
					if (oc) {
						int firstone = (i - oc) - 200;	
						int bit = firstone / 71;

						int offset = firstone - (bit * 71);
						if ((offset > 15) && (offset < 65)) {
							code |= (1 << (23 - bit));
						}

						cerr << cline << ' ' << i << ' ' << firstone << ' ' << bit * 71 << ' ' << bit << ' ' << hex << code << dec << endl;
						lastone = i;
					}
					oc = 0;
				}
				i++;
			}
			cerr << "P " << cline << ' ' << hex << code << dec << endl;
			return code;
		}

		NTSColor(vector<YIQ> *_buf = NULL, Filter *_f_post = NULL, Filter *_f_postc = NULL, int _freq = 10) {
			counter = 0;
			phased = insync = false;

			fieldcount = 0;
			cline = 0;

			pix_poffset = poffset = 0;
			adjfreq = 1.0;

			lastline = lastsync = -1;

			level = phase = 0.0;

			freq = _freq;

			buf = _buf;

			prev_igap = igap = -1;
					
			buf_1h.resize(2275);
			prev.resize(40);
	
			for (int e = 0; e < freq; e++) {
				_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / (double)freq)));
				_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / (double)freq)));
				_cosp[e] = cos(phase + (2.0 * M_PIl * ((((double)e) - 2.5) / (double)freq)));
				_sinp[e] = sin(phase + (2.0 * M_PIl * ((((double)e) - 2.5) / (double)freq)));
			}

                        f_i = new Filter(37, NULL, f35_1_3mhz_b37);
                        f_q = new Filter(37, NULL, f35_1_3mhz_b37);

                        f_synci = new Filter(81, NULL, f35_0_6mhz_b81);
                        f_syncq = new Filter(81, NULL, f35_0_6mhz_b81);

			f_linelen = new Filter(8, NULL, f_hsync8);
			for (int i = 0; i < 9; i++) f_linelen->feed(2175);
	
			f_post = _f_post ? new Filter(*_f_post) : NULL;
		}

		void write() {
#ifndef RAW
			for (int i = 0; i < (1930 * 480); i++) {
				if (buf && ((i % 1930) >= 10)) buf->push_back(frame[i]);
			} 
			memset(frame, 0, sizeof(frame));
			cerr << "written\n";
#endif
		}

		void bump_cline() {
			cline++;
				
//			if (NTSCLine[cline] && LINE_NORMAL) lastsync = 0; 
	
			if ((cline == 263) || (cline == 526)) {
				fieldcount++;
				cerr << "fc " << fieldcount << endl;

				if (fieldcount == 2) {
					write();
					fieldcount = 0;
				}
			}
			if (cline == 526) cline = 1;
		}

		void feed(double in) {
			double dn = (double) in / 62000.0;
	
			if (!dn) {
				dn = buf_1h[counter % 2275]; 
			}

			buf_1h[counter % 2275] = dn;

			counter++;
			if (lastsync >= 0) lastsync++;

//			cerr << insync << ' ' << lastsync << endl;
			
			prev[counter % 40] = dn;

			int count = 0;
			if (insync == false) {
				for (int i = 0; i < 40; i++) {
					if (prev[i] < 0.1) {
						count++;
					}
				}
//				if (count >= 16) cerr << cline << " sync at 1 " << counter - 16 << ' ' << igap << ' ' << insync << endl;
				if (count >= 30) {
					if ((igap > 1100) && (igap < 1175)) {
						if ((cline <= 0) && (prev_igap >= 2250)) {
							cline = 1;
							lastline = counter;
						} 
					} else {
						if (buf && (NTSCLine[cline] & LINE_WHITEFLAG)) {
							if (whiteflag_decode()) {
								cerr << "whiteflag " << cline << endl;
								fieldcount = 0;	
							}
						}
/*						if (0 && buf && (cfline >= 6) && (cfline <= 8)) {
							unsigned long pc = phillips_decode() & 0xff0000;
							if (pc == 0xf80000 || pc == 0xfa0000 || pc == 0xf00000) {
								fieldcount = 0;
							}					
						}
*/						if ((igap > 2225) && (igap < 2325)) {
							f_linelen->feed(igap);
							if ((cline >= 1) && ((counter - lastline) > 2250)) {
								lastline = counter;
								bump_cline();
							}
						}
					}
				
					prev_igap = igap;	
					igap = lastsync;

					lastsync = 0;
					peaksynci = peaksyncq = peaksync = 0;

					cerr << cline << ' ' << NTSCLineLoc[cline] << " sync at " << counter - 24 << ' ' << igap << ' ' << insync << endl;
					insync = true;
					prev.clear();
					line.clear();
				}
					
				line.push_back(dn);

				if ((NTSCLine[cline] & LINE_NORMAL) && (igap < 2400) && lastsync == 310) {
					fc = peaksyncq;
					fci = peaksynci;
					level = peaksync;
					cerr << level << endl;
					if ((level > .04) && (level < .15)) {
						double padj = atan2(fci, ctor(fc, fci));

						if (fc > 0) {
							if (igap > 2275) 
								padj = (M_PIl / 2.0) - padj; 
							else {
								padj = -(M_PIl / 2.0) - padj; 
							}
						}

						phase -= (padj * sqrt(2.0));
						phased = true;
						phase_count = counter;

						for (int e = 0; e < freq; e++) {
							_cos[e] = cos(phase + (2.0 * M_PIl * ((double)e / freq)));
							_sin[e] = sin(phase + (2.0 * M_PIl * ((double)e / freq)));
							// 2.5 is 1/4 phase, and another 1 for timing compensation
							_cosp[e] = cos(phase + (2.0 * M_PIl * (((double)e - 2.5)/ freq)));
							_sinp[e] = sin(phase + (2.0 * M_PIl * (((double)e - 2.5)/ freq)));
						}

						pix_poffset = phase / M_PIl * 5.0;
						poffset += (igap - 2275);	

						if (tbc == TBC_HSYNC) {
							adjfreq = 2275.0 / f_linelen->val();
						} else {
							adjfreq = 2275.0 / (2275 + (padj * (M_PIl / 1.5)));
						}
					}

					//cerr << (buf ? 'B' : 'A') << ' ' ;
					//cerr << counter << " level " << level << " q " << fc << " i " << fci << " phase " << atan2(fci, ctor(fc, fci)) << " adjfreq " << adjfreq << ' ' << igap << ':' << f_linelen->val() << ' ' << poffset - pix_poffset << endl ;
				} else {
//					if (buf && lastsync == 200 && igap >= 0) cerr << "S " << counter << ' ' << igap << endl;
				}
			} else {
				for (int i = 0; i < 40; i++) {
					if (prev[i] > 0.2) count++;
				}
				if (count >= 20) {
					insync = false;
					prev.clear();
					fc = fci = 0;
				}
			}

			// yes, repeating this 2-4 times is in fact a huge bottleneck!
			int cf = counter % freq;

                        double q = f_q->feed(dn * _cos[cf]);
			double i = f_i->feed(-dn * _sin[cf]);

//			cerr << dn << ' ' << i << ' ' << q << endl;
                       
			if ((lastsync > 125) && (lastsync < 310)) { 
				double q = f_syncq->feed(dn * _cos[cf]);
				double i = f_synci->feed(-dn * _sin[cf]);

				double synclev = ctor(i, q);

				if (synclev > peaksync) {
					peaksynci = i;
					peaksyncq = q;
					peaksync = synclev;
				}
			}

			// Automatically jump to the next line on HSYNC failure
			if ((cline >= 1) && ((counter - lastline) == 2600)) {
				lastline += 2275;
				bump_cline();
			}

//			cerr << _cos[counter % 8] << ' ' << cos(phase + (2.0 * M_PIl * ((double)(counter) / freq))) << endl;

//                      double q = f_q->feed(dn * cos(phase + (2.0 * M_PIl * ((double)(counter) / freq))));
//			double i = f_i->feed(-dn * sin(phase + (2.0 * M_PIl * ((double)(counter) / freq))));

			if (buf && (lastsync >= 0)) {
				double _y = dn, y = dn;

				if (counter > 20) {
					_y = circbuf[counter % 20];
				}
				circbuf[counter % 20] = y;

				y = _y;

#ifndef BW
				int c10 = counter % 10;

				double iadj = i * 2 * _cosp[c10];
				double qadj = q * 2 * _sinp[c10]; 
//				cerr << "p " << lastsync << ' ' << ctor(i, q) << ' ' << (atan2(i, ctor(i,q)) / (M_PIl / 180.0)) + 180.0 << " iadj " << iadj << " qadj " << qadj << " y " << y << " " << iadj + qadj;
				//cerr << "p " << atan2(i, q) << " iadj " << iadj << " qadj " << qadj << " y " << y;
			
//				cerr << y << ' ' << iadj << ' ' << qadj;
				y += iadj + qadj;
//				cerr << " " << y << endl;

				if (f_post) y = f_post->feed(y);

//				cerr << (.1 / level) << endl;
//				YIQ outc = YIQ(y, (.1 / level) * i, (.1 / level) * q);
				YIQ outc = YIQ(y, 4 * i, 4 * q);
#else
				YIQ outc = YIQ(y, 0,0);
#endif
				if (!lastsync) outc.y = 1.0;

#ifdef RAW
				buf->push_back(outc);			
#else
				if ((NTSCLineLoc[cline] >= 0) && (lastsync > 315) && (lastsync < (315 + 1930)) ) {
//					cerr << cline << ' ' << lastsync << endl;
					frame[(NTSCLineLoc[cline] * 1930) + (lastsync - 315)].y = outc.y;
					frame[(NTSCLineLoc[cline] * 1930) + (lastsync - 315) + 10].i = outc.i;
					frame[(NTSCLineLoc[cline] * 1930) + (lastsync - 315) + 10].q = outc.q;
				}
#endif
			}
	//		return YIQ();
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	unsigned short inbuf[2048];

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
		
	if (argc >= 3) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	buildNTSCLines();

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
/*	
	Filter f_hp35(14, NULL, f_hp35_14_b);
	Filter f_lpf30(32, f_lpf30_b7_a, f_lpf30_b7_b);
	Filter f_lpf02(4, f_lpf048_b4_a, f_lpf048_b4_b);
	Filter f_butter6(6, f_butter6_a, f_butter6_b);
	Filter f_butter8(8, f_butter8_a, f_butter8_b);
	Filter f_boost6(8, NULL, f_boost6_b);
	Filter f_boost8(8, NULL, f_boost8_b);
	Filter f_boost16(8, NULL, f_boost16_b);

	Filter f_lpf49(8, NULL, f_lpf49_8_b);
	Filter f_lpf45(8, NULL, f_lpf45_8_b);
	Filter f_lpf40(12, NULL, f_lpf40_12_hamming_b);
	Filter f_lpf13(8, NULL, f_lpf13_8_b);
*/
	Filter f_lpf40(15, NULL, f_lpf40_15_hamming_b);

	vector<YIQ> outbuf;	

	NTSColor *color = new NTSColor(&outbuf, &f_lpf40);

	int count = 0;

	while ((rv > 0) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		vector<unsigned short> bout;

		for (int i = 0; i < (rv / 2); i++) {
			int in = inbuf[i];

			count++;
			color->feed(in);
		}
		
		i += rv;
		if (i % 2) inbuf[0] = inbuf[rv];
		rv = read(fd, &inbuf[i % 2], 2048 - (i % 2));

		for (YIQ i : outbuf) {
			RGB r;
			r.conv(i);
			bout.push_back(r.r * 62000.0);
			bout.push_back(r.g * 62000.0);
			bout.push_back(r.b * 62000.0);
		}
		outbuf.clear();

		unsigned short *boutput = bout.data();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}
	}

	return 0;
}
