#!/bin/bash
# Usage: ./check_pgssub.sh "input.mkv"

INPUT="$1"
if [ -z "$INPUT" ]; then
  echo "Usage: $0 input.mkv"
  exit 1
fi

# Count subtitle streams
NUM_SUBS=$(ffprobe -v error -select_streams s -show_entries stream=index -of csv=p=0 "$INPUT")

for SID in $NUM_SUBS; do
  echo -n "Testing subtitle stream #$SID ... "
  ffmpeg -nostdin -v error -analyzeduration 200M -probesize 200M -i "$INPUT" -map 0:s:$SID -c copy -f null - 2> /dev/null
  if [ $? -ne 0 ]; then
    echo "BROKEN"
  else
    echo "OK"
  fi
done
