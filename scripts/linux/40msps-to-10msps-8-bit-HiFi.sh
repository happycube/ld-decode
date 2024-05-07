    #!/bin/bash

    echo "Conversion of 10-bit 40msps .lds to 8-bit 10msps PAL .flac has 
    started"

    ld-lds-converter -i $1 | sox -r 40000 -b 16 -c 1 -e signed -t raw - -b 8 -r 10000 -c 1 -t flac $1_VHS_HiFi_10msps_8-bit.flac sinc -n 2500 0-3050