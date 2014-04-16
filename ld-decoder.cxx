/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

const double CHZ = (1000000.0*(315.0/88.0)*8.0);

const double f_lpf42_16_python_b[] {2.806676426568827e-03 , 8.678237335678843e-04 , -7.758994442967244e-03 , -2.292786181447184e-02 , -2.214853573118029e-02 , 2.782699125184042e-02 , 1.319713476036243e-01 , 2.434340451329033e-01 , 2.918570156802296e-01 , 2.434340451329033e-01 , 1.319713476036244e-01 , 2.782699125184043e-02 , -2.214853573118030e-02 , -2.292786181447184e-02 , -7.758994442967246e-03 , 8.678237335678851e-04 , 2.806676426568827e-03};

const double f_lpf45_16_python_b[] { 3.165390390504862e-03 , 3.060141452169122e-03 , -3.984544684717678e-03 , -2.248680062518488e-02 , -3.091815939876376e-02 , 1.350373945897430e-02 , 1.260523263298884e-01 , 2.551817689904604e-01 , 3.128522761733384e-01 , 2.551817689904605e-01 , 1.260523263298884e-01 , 1.350373945897431e-02 , -3.091815939876376e-02 , -2.248680062518488e-02 , -3.984544684717680e-03 , 3.060141452169125e-03 , 3.165390390504862e-03 };

const double f_lpf45_17_python_b[] { 3.165390390504862e-03 , 3.060141452169122e-03 , -3.984544684717678e-03 , -2.248680062518488e-02 , -3.091815939876376e-02 , 1.350373945897430e-02 , 1.260523263298884e-01 , 2.551817689904604e-01 , 3.128522761733384e-01 , 2.551817689904605e-01 , 1.260523263298884e-01 , 1.350373945897431e-02 , -3.091815939876376e-02 , -2.248680062518488e-02 , -3.984544684717680e-03 , 3.060141452169125e-03 , 3.165390390504862e-03 };

const double f_lpf50_16_python_b[] {1.916071020215727e-03 , 5.134814884462994e-03 , 3.347495595196464e-03 , -1.653628437323453e-02 , -4.060917271174611e-02 , -1.128852987551174e-02 , 1.114703592770741e-01 , 2.724978912765220e-01 , 3.481347098140423e-01 , 2.724978912765220e-01 , 1.114703592770741e-01 , -1.128852987551175e-02 , -4.060917271174612e-02 , -1.653628437323453e-02 , 3.347495595196465e-03 , 5.134814884462999e-03 , 1.916071020215727e-03};

const double f_lpf50_18_b[] {2.978058964677272e-04 , 4.380676214424168e-03 , 7.333573824780148e-03 , -4.775776767572557e-03 , -3.425670273808993e-02 , -3.886348879842556e-02 , 4.035115169608995e-02 , 1.967125430682141e-01 , 3.288202176041120e-01 , 3.288202176041120e-01 , 1.967125430682141e-01 , 4.035115169608997e-02 , -3.886348879842557e-02 , -3.425670273808992e-02 , -4.775776767572560e-03 , 7.333573824780159e-03 , 4.380676214424168e-03 , 2.978058964677272e-04};

#include "deemp.h"

Filter f_lpf(18, NULL, f_lpf50_18_b);

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
			double total = 0.0;
			
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			if (in.size() < (size_t)linelen) return out;

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

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

				if (f_post) thisout = f_post->feed(pf);	
				if (i > min_offset) {
					int bin = (thisout - 7600000) / 200000;
					if (1 || bin < 0) bin = 0;

					avglevel[bin] *= 0.9;
					avglevel[bin] += level[npeak] * .1;

					out.push_back(((level[npeak] / avglevel[bin]) > 0.3) ? thisout : 0);
				};
				i++;
			}

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
	
	Filter f_boost36(36, NULL, f_boost36_b);

	FM_demod video(2048, {8100000, 8500000, 8900000, 9300000, 9700000}, {&f_boost36}, {&f_lpf, &f_lpf, &f_lpf, &f_lpf, &f_lpf, &f_lpf}, NULL);

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
				n = f_deemp.feed(n) ;

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

