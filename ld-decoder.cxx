/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

// b = fir2(32, [0 (3.2/freq) (7.5/freq) (10/freq) (12.5/freq) 1], [0 -.00 1.4 2 0.1 0]); freqz(b)
const double f_boost32_b[] {-7.505745521587810e-04, 5.880141228167600e-04, 3.633494160512888e-04, -4.753259366138748e-04, 1.053434572099664e-03, 1.340894904905588e-03, -4.702405740632102e-03, -2.706299231274282e-03, 8.994775695048057e-03, -2.926960441646054e-02, 3.944247868805379e-02, 5.763183590423128e-04, -3.491893007597012e-02, 2.161049229761215e-01, -3.515066791863503e-01, -1.927783083546432e-01, 6.967256565174642e-01, -1.927783083546432e-01, -3.515066791863503e-01, 2.161049229761215e-01, -3.491893007597013e-02, 5.763183590423131e-04, 3.944247868805381e-02, -2.926960441646055e-02, 8.994775695048059e-03, -2.706299231274281e-03, -4.702405740632101e-03, 1.340894904905589e-03, 1.053434572099664e-03, -4.753259366138747e-04, 3.633494160512898e-04, 5.880141228167604e-04, -7.505745521587810e-04};

const double f_boost16_b[] {1.332559362229342e-03, -5.345773532279951e-03, 1.182836806945454e-02, 2.636626542153173e-04, -2.179232081607182e-02, 1.677426303390736e-01, -3.151841796082856e-01, -1.876870184544854e-01, 6.967256565174642e-01, -1.876870184544854e-01, -3.151841796082856e-01, 1.677426303390737e-01, -2.179232081607183e-02, 2.636626542153174e-04, 1.182836806945454e-02, -5.345773532279956e-03, 1.332559362229342e-03};

const double f_boost24_b[] {3.924669125894978e-04, 4.510265100480637e-04, -1.829826113723156e-03, -1.290649880814969e-03, 5.163667528638698e-03, -1.956491854690395e-02, 2.974569255267883e-02, 4.774315065423310e-04, -3.107423523773203e-02, 2.027032811687872e-01, -3.418126260665363e-01, -1.914488505853340e-01, 6.967256565174642e-01, -1.914488505853340e-01, -3.418126260665364e-01, 2.027032811687872e-01, -3.107423523773205e-02, 4.774315065423312e-04, 2.974569255267884e-02, -1.956491854690396e-02, 5.163667528638698e-03, -1.290649880814969e-03, -1.829826113723158e-03, 4.510265100480643e-04, 3.924669125894977e-04  };

const double f_lpf50_16_python_b[] {0.00191607102022 , 0.00513481488446 , 0.0033474955952 , -0.0165362843732 , -0.0406091727117 , -0.0112885298755 , 0.111470359277 , 0.272497891277 , 0.348134709814 , 0.272497891277 , 0.111470359277 , -0.0112885298755 , -0.0406091727117 , -0.0165362843732 , 0.0033474955952 , 0.00513481488446 , 0.00191607102022};

//const double f_lpf50_32_python_b[] {-0.00153514027372 , -0.00128484804517 , 0.000896191796755 , 0.00383478453322 , 0.00321506486168 , -0.0039443397662 , -0.0116050394341 , -0.00692331358262 , 0.0129993404531 , 0.0282577143598 , 0.011219288771 , -0.0363293568899 , -0.0654014729708 , -0.0146172118449 , 0.124949497855 , 0.281315083295 , 0.349907513762 , 0.281315083295 , 0.124949497855 , -0.0146172118449 , -0.0654014729708 , -0.0363293568899 , 0.011219288771 , 0.0282577143598 , 0.0129993404531 , -0.00692331358262 , -0.0116050394341 , -0.0039443397662 , 0.00321506486168 , 0.00383478453322 , 0.000896191796755 , -0.00128484804517 , -0.00153514027372 };

const double f_lpf55_16_python_b[] {-0.000723397637219 , 0.00433368634435 , 0.00931049560886 , -0.00571459940902 , -0.0426674090828 , -0.0349785521301 , 0.0915883051498 , 0.286887403184 , 0.383928135944 , 0.286887403184 , 0.0915883051498 , -0.0349785521301 , -0.0426674090828 , -0.00571459940902 , 0.00931049560886 , 0.00433368634435 , -0.000723397637219};

const double f_butter_a[] {1.000000000000000e+00, -2.398290348480684e+00, 3.391618205402128e+00, -2.989615889615524e+00, 1.815339383739279e+00, -7.463848760799012e-01, 2.029423253178536e-01, -3.282557852899168e-02, 2.415500405308583e-03};

const double f_butter_b[] {9.578075084354191e-04, 7.662460067483353e-03, 2.681861023619173e-02, 5.363722047238347e-02, 6.704652559047933e-02, 5.363722047238347e-02, 2.681861023619173e-02, 7.662460067483353e-03, 9.578075084354191e-04};

//Filter f_lpf(16, NULL, f_lpf55_16_python_b);
Filter f_lpf(8, f_butter_a, f_butter_b);

// From http://lists.apple.com/archives/perfoptimization-dev/2005/Jan/msg00051.html. 
const double PI_FLOAT = M_PIl;
const double PIBY2_FLOAT = (M_PIl/2.0); 
// |error| < 0.005
double fast_atan2( double y, double x )
{
	if ( x == 0.0f )
	{
		if ( y > 0.0f ) return PIBY2_FLOAT;
		if ( y == 0.0f ) return 0.0f;
		return -PIBY2_FLOAT;
	}
	double atan;
	double z = y/x;
	if (  fabs( z ) < 1.0f  )
	{
		atan = z/(1.0f + 0.28f*z*z);
		if ( x < 0.0f )
		{
			if ( y < 0.0f ) return atan - PI_FLOAT;
			return atan + PI_FLOAT;
		}
	}
	else
	{
		atan = PIBY2_FLOAT - z/(z*z + 0.28f);
		if ( y < 0.0f ) return atan - PI_FLOAT;
	}
	return atan;
}


typedef vector<complex<double>> v_cossin;

class FM_demod {
	protected:
		double ilf;
		vector<Filter> f_q, f_i;
		vector<Filter *> f_pre;
		Filter *f_post;

		vector<v_cossin> ldft;
		double avglevel[40];

		double cbuf[9];
	
		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod(int _linelen, vector<double> _fb, vector<Filter *> prefilt, vector<Filter *> filt, Filter *postfilt) {
			int i = 0;
			linelen = _linelen;

			fb = _fb;

			ilf = 8600000;
			deemp = 0;

			for (double f : fb) {
				v_cossin tmpdft;
				double fmult = f / CHZ; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
					// cerr << sin(i * 2.0 * M_PIl * fmult) << ' ' << cos(i * 2.0 * M_PIl * fmult) << endl;
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(Filter(filt[i]));
				f_q.push_back(Filter(filt[i]));

				i++;
			}

			f_pre = prefilt;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			for (int i = 0; i < 40; i++) avglevel[i] = 30;
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			min_offset = 128;
		}

		~FM_demod() {
//			if (f_pre) free(f_pre);
			if (f_post) free(f_post);
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(fb.size() + 1);
			vector<double> level(fb.size() + 1);
			double avg = 0, total = 0.0;
			
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();
			//cerr << avg << endl;

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

			//	n -= avg;
				total += fabs(n);
				for (Filter *f: f_pre) {
					n = f->feed(n);
				}

				angle[j] = 0;

//				cerr << i << ' ';
	
				for (double f: fb) {
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
					double at2 = fast_atan2(fci, fcq);	
	
//					cerr << n << ' ' << fci << ' ' << fcq << ' ' ;

					level[j] = ctor(fci, fcq);
	
					angle[j] = at2 - phase[j];
					if (angle[j] > M_PIl) angle[j] -= (2 * M_PIl);
					else if (angle[j] < -M_PIl) angle[j] += (2 * M_PIl);
					
//					cerr << at2 << ' ' << angle[j] << ' '; 
				//	cerr << angle[j] << ' ';
						
					if (fabs(angle[j]) < fabs(peak)) {
						npeak = j;
						peak = angle[j];
						pf = f + ((f / 2.0) * angle[j]);
					}
//					cerr << pf << endl;
					phase[j] = at2;

				//	cerr << f << ' ' << pf << ' ' << f + ((f / 2.0) * angle[j]) << ' ' << fci << ' ' << fcq << ' ' << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	
//				cerr << pf << endl;

				if (f_post) thisout = f_post->feed(pf);	
				if (i > min_offset) {
					int bin = (thisout - 7600000) / 200000;
					if (1 || bin < 0) bin = 0;

					avglevel[bin] *= 0.9;
					avglevel[bin] += level[npeak] * .1;

//					if (fabs(shift) > 50000) thisout += shift;
//					cerr << ' ' << thisout << endl ;
//					out.push_back(((level[npeak] / avglevel[bin]) * 1200000) + 7600000); 
//					out.push_back((-(level[npeak] - 30) * (1500000.0 / 10.0)) + 9300000); 
					out.push_back(((level[npeak] / avglevel[bin]) > 0.3) ? thisout : 0);
//					out.push_back(thisout);
				};
				i++;
			}

//			cerr << total / in.size() << endl;
			return out;
		}
};

bool triple_hdyne = true;

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1;
	//double output[2048];
	unsigned char inbuf[2048];

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
		if ((size_t)atoll(argv[3]) < dlen) {
			dlen = atoll(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	Filter f_boost16(16, NULL, f_boost16_b);
	Filter f_boost24(24, NULL, f_boost24_b);
	Filter f_boost32(32, NULL, f_boost32_b);

	FM_demod video(2048, {8100000, 8600000, 9100000, 9600000}, {&f_boost24}, {&f_lpf, &f_lpf, &f_lpf, &f_lpf, &f_lpf}, NULL);

	double charge = 0, acharge = 0, prev = 8700000;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			int in;

			if (n > 0) {
//				cerr << i << ' ' << n << ' ';
				charge += ((n - prev) * 1.0);
				acharge += fabs((n - prev) * 1.0);
				prev = n;

				double f = .48;

				if (fabs(acharge) < 500000) f += (0.52 * (1.0 - (fabs(acharge) / 500000.0)));

				n -= (charge * f);
//				n -= (charge * .5);
//				cerr << n << ' ' << charge << ' ' << adj << ' ';
				charge *= 0.88;
				acharge *= 0.88;
//				cerr << charge << ' ' << endl;

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 57344.0);
				if (in > 65535) in = 65535;
//				cerr << in << endl;
			} else {
				in = 0;
			}

			bout.push_back(in);
		}
		
		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		i += (len > 1820) ? 1820 : len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		//cerr << i << ' ' << rv << endl;
	}
	return 0;
}

