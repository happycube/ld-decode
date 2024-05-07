    #!/bin/bash

    echo "Conversion of 10-bit 40msps .lds to 8-bit 20msps PAL .flac has 
    started"

    $1 sox -r 40000 -b 8 -c 1 -e signed -t raw - -b 8 -r 20000 -c 1 -t flac $1_20msps_8-bit.flac sinc -n 2500 0-9650