#include <stdio.h>
#include <unistd.h>
#include <stdint.h>

// in number of samples - must be divisible by 3
#define BUFSIZE 32768 
	
uint32_t inbuf[BUFSIZE];
int16_t outbuf[BUFSIZE * 3];

int16_t extend(uint32_t sample) 
{
	uint16_t uout = (uint16_t)(sample & 0x3ff);
	int16_t out = uout - 512;

	out = out << 6;

	// add the last 6 bits if signed
	//if (out & 0x8000) out |= 0x3f;
	return (int16_t)out;
}

int main(void)
{
	size_t rv = 0;
	int i, o = 0;

	while ((rv = fread(inbuf, sizeof(uint32_t), BUFSIZE, stdin)) > 0) {
		o = 0;
		for (i = 0; i < rv; i++) {
			outbuf[o++] = extend(inbuf[i]);
			outbuf[o++] = extend(inbuf[i] >> 10);
			outbuf[o++] = extend(inbuf[i] >> 20);
		}
		rv = fwrite(outbuf, sizeof(int16_t), o, stdout);
	}
}

