#include <stdio.h>
#include <unistd.h>
#include <stdint.h>

// in number of samples - must be divisible by 3
#define BUFSIZE 4096*3 
	
int16_t inbuf[BUFSIZE];
uint32_t outbuf[BUFSIZE / 3];

inline uint16_t sconv(int16_t sample) 
{
	uint32_t usample = (uint32_t)sample + 32768;
	return (((unsigned int)usample) >> 6) & 0x3ff;
}

int main(void)
{
	size_t rv, ilen = 0;
	int i;

	while ((rv = fread(inbuf, sizeof(int16_t), BUFSIZE, stdin)) > 0) {
		for (i = 0; i < (rv / 3); i++) {
			outbuf[i] = sconv(inbuf[(i * 3)]) << 0;
			outbuf[i] |= sconv(inbuf[(i * 3) + 1]) << 10;
			outbuf[i] |= sconv(inbuf[(i * 3) + 2]) << 20;
		}
		rv = fwrite(outbuf, sizeof(uint32_t), i, stdout);
	}
}

