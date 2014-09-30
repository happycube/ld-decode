/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

const double CHZ = (1000000.0*(315.0/88.0)*8.0);

#include "deemp.h"

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

inline double WrapAngle(double a1, double a2) {
        double v = a2 - a1;

        if (v > M_PIl) v -= (2 * M_PIl);
        else if (v <= -M_PIl) v += (2 * M_PIl);

        return v;
}

class FM_demod {
	protected:
		Filter *f_pre;
		Filter *f_post;

		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod(int _linelen, Filter *prefilt, Filter *postfilt) {
			int i = 0;
			linelen = _linelen;

			deemp = 0;

			f_pre = prefilt;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

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
			
			if (in.size() < (size_t)linelen) return out;

			double prev_ang = 0;

			int i = 0;
			for (double n : in) {
				double v = 0;	

				n = f_pre->feed(n);

				double real = f_hilbertr.feed(n);
				double imag = f_hilberti.feed(n);

				double ang = atan2(real, imag);
		
				if (!i) prev_ang = ang;

				double diff = WrapAngle(ang, prev_ang);

				v = diff * 4557618;
				if (f_post) v = f_post->feed(v);	

			//	cerr << ang << ' ' << diff << ' ' << diff * 4557618 << ' ' << v << endl;

				prev_ang = ang;

				if (i > 1024) out.push_back(v);

				i++;
			}

			return out;
		}
};

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

#if 0
	for (int i = 0 ; i < 4096; i++) {
		double n = 9300000;

		cerr << "d " << n ;
		n = f_deemp.feed(n) ;
		cerr << " " << n / 0.9919 << endl;
	}
	return -1;
#endif

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	FM_demod video(2048, &f_boost, &f_lpf);

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
		//		cerr << "d " << n ;
				n = f_deemp.feed(n) / .4960;
		//		cerr << " " << n << endl;

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 57344.0);
				if (in > 64000) in = 64000;
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

