#!/bin/bash

modeselection=0
comp=true
uncomp=false
verify=false
fileinput_method=cat
level=11
ext=ldf

help_msg () {
  echo "Usage: $0 [-c] [-u] [-v] [-p] [-h] [-l <1-15>] [-g] file(s)"; printf -- "\nModes:\n-c Compress (default): Takes one or more .lds files and compresses them to .ldf files in the current directory.\n-u Uncompress: Takes one or more .ldf/.raw.oga files and uncompresses them to .lds files in the current directory.\n-v Verify: Returns md5 checksums of the given .ldf/.raw.oga files and their contained .lds files for verification purposes.\n\nOptions\n-p Progress: displays progress bars - requires pv to be installed.\n-h Help: This dialog.\n-l Compression level 1 - 12. Default is 11. 6 is recommended for faster but fair compression.\n-g Use .raw.oga extension instead of .ldf when compressing.\n\n"
}

while getopts ":hcuvpl:g" option; do
  case $option in
    h) help_msg ; exit ;;
    c) comp=true ; modeselection=$((modeselection+1)) ;;
    u) uncomp=true ; comp=false ; modeselection=$((modeselection+1)) ;;
    v) verify=true ; comp=false ; modeselection=$((modeselection+1)) ;;
    p) fileinput_method="pv" ;;
    l)
      level=${OPTARG}
      if [ $level -gt 0 -a $level -le 12 ]
      then
        >&2 echo "Compression level: $level"
      else
        help_msg
        >&2 echo "Error: invalid compression level: $level."
        exit
      fi
      ;;
    g) ext=raw.oga ;;
    ?) help_msg ; exit ;;
  esac
done


# remove the options from the positional parameters
shift $(( OPTIND - 1 ))

# Check if input files have been entered, and if so, process according to the selected mode.
if [[ $# < 1 ]]
then
  help_msg ; exit
else
  if (($modeselection > 1)) # more than a single mode is selected
  then
    help_msg
    >&2 echo Error: Incompatible options. ; exit
  else
    trap exit SIGINT SIGTERM #Exit on ctrl-c
    if [[ "$comp" == true ]] # Perform compression
    then
      for f in "$@" ; do
        if [[ "$f" == *.lds ]]
        then
          >&2 echo Compressing \'"$f"\' to \'"$(basename "$f" .lds).$ext"\' && ${fileinput_method} "$f" | ld-lds-converter -u |  ffmpeg -hide_banner -loglevel error -f s16le -ar 40k -ac 1 -i - -acodec flac -compression_level "$level" -f ogg "$(basename "$f" .lds).$ext"
        else
          >&2 echo Error: \'"$f"\' does not appear to be a .lds file. Skipping.
        fi
      done
    fi
    if [[ "$uncomp" == true ]] # Perfom uncompression
    then
      for f in "$@" ; do
        if [[ "$f" == *.raw.oga || "$f" == *.ldf ]]
        then
         >&2 echo Uncompressing \'"$f"\' && ${fileinput_method} "$f" | ffmpeg -hide_banner -loglevel error -i - -f s16le -c:a pcm_s16le - | ld-lds-converter -p -o "$(basename ${f%.raw.oga} .ldf).lds"
        else
         >&2 echo Error: \'"$f"\' does not appear to be a .raw.oga/.ldf file. Skipping.
        fi
      done
    fi
  fi
  if [[ "$verify" == true ]] # Perform MD5 check of contents.
  then
    for f in "$@" ; do
      if [[ "$f" == *.raw.oga || "$f" == *.ldf ]]
      then
        sleep 1 # Give any previous iteration a second to output.
        >&2 echo "Performing checksum of" \'"$f"\': && ${fileinput_method} "$f" | tee >(openssl dgst -md5 | echo $(awk '{print $2}') " $f") >(ffmpeg -hide_banner -loglevel error -f ogg -i - -f s16le -c:a pcm_s16le - | ld-lds-converter -p | openssl dgst -md5 | echo $(awk '{print $2}') " $(basename ${f%.raw.oga} .ldf).lds") > /dev/null
      else
        sleep 1
        >&2 echo Error: \'"$f"\' does not appear to be a .raw.oga/.ldf file. Skipping.
      fi
    done
  fi
  sleep 1
  >&2 echo "Task complete."
fi
