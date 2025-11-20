#!/bin/bash
#exit

# Input file
input_file="$1"

# Extract pixel format using ffprobe and trim any excess whitespace or lines
pix_fmt=$(ffprobe -hide_banner -v error -select_streams v:0 -show_entries stream=pix_fmt -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null | head -n 1 | xargs)
#pix_fmt="yuv422p"

# Determine the appropriate profile based on the pixel format
profile="high"
if [[ "$pix_fmt" == *"yuv420p10le"* ]]; then
    profile="high10"
fi
#profile="high422"

# Check if the video is interlaced using ffprobe
field_order=$(ffprobe -hide_banner -v error -select_streams v:0 -show_entries stream=field_order -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null | head -n 1)
echo "field_order='$field_order'"

# If the field order does not indicates progressive video, enable deinterlacing
deinterlace_filter="-vf yadif"
if [[ "$field_order" == *"progressive"* ]]; then
    deinterlace_filter=""
fi

# Quality for H.264
# CRF 18–20: High quality
# CRF 21–24: Balanced
# CRF 25–28: Smaller size, lower quality
crf=21
preset="veryslow"  # at least "medium"
preset_tag="vs"
#crf=18

# Quality for AAC
# VBR 5-0: highest to lowest quality
vbr=5

# Create the subfolders and store paths
output_dir="$(dirname "$input_file")/komp"
mkdir -p "$output_dir"
log_dir="$(dirname "$input_file")/log"
mkdir -p "$log_dir"

encoded_file="$output_dir/$(basename "${input_file%.*}") [crf-${crf}] [p-${preset_tag}] [vbr-${vbr}] [vc-h264] [ac-aac] [sc-n].mkv"
remuxed_file="${encoded_file// \[sc-n\]/}"
fflog_file="$log_dir/$(basename "${input_file%.*}").fflog"

# Display used settings.
echo "input_file='$input_file'"
echo "crf='$crf'"
echo "vbr='$vbr'"
echo "profile='$profile'"
echo "pix_fmt='$pix_fmt'"
echo "deinterlace_filter='$deinterlace_filter'"
echo "preset='$preset'"

# Run the ffmpeg command dynamically based on the input file's pixel format and profile,
# preserving all audio and subtitle tracks without re-encoding the audio.
# https://trac.ffmpeg.org/wiki/Encode/AAC
# (libfdk_aac required for setting target quality)
cmd1=(ffmpeg -nostdin \
    -i "$input_file" \
    -map 0:v -c:v libx264 -crf "$crf" -preset "$preset" -profile:v "$profile" -pix_fmt "$pix_fmt" $deinterlace_filter \
    -map 0:a -c:a libfdk_aac -vbr "$vbr" \
    -sn \
    "$encoded_file")

# Optional:
#-vf "scale=1920:-2:flags=lanczos"

echo "${cmd1[@]}"
encoding_failed="0"
if ! "${cmd1[@]}" 2> "$fflog_file"
then
    encoding_failed="1"
fi

# Get durations (strip warning, keep only last line)
input_duration=$(ffprobe -show_entries format=duration -v quiet -of csv="p=0" -sexagesimal -i "$input_file" 2>&1 | tail -n1 | tr -d "\n")
encoded_duration=$(ffprobe -show_entries format=duration -v quiet -of csv="p=0" -sexagesimal -i "$encoded_file" 2>&1 | tail -n1 | tr -d "\n")
# Get file sizes in GB (two decimals)
input_size_gib=$(du -b "$input_file" | awk '{printf "%.2f", $1/1024/1024/1024}')
encoded_size_gib=$(du -b "$encoded_file" | awk '{printf "%.2f", $1/1024/1024/1024}')
# Calculate reduction rate
filesize_reduction_rate=$(awk -v in_size="$input_size_gib" -v out_size="$encoded_size_gib" 'BEGIN { printf "-%.1f%%", (1 - out_size/in_size)*100 }')

# Remux encoding with original subtitles, if not failed
remux_failed="0"
if [[ "$encoding_failed" == "0" ]]; then
    cmd2=(ffmpeg -nostdin \
        -fflags +genpts -avoid_negative_ts make_zero -max_interleave_delta 0 \
        -i "$encoded_file" \
        -i "$input_file" \
        -map 0:v \
        -map 0:a \
        -map 1:s? \
        -c copy \
        "$remuxed_file")

    echo "${cmd2[@]}"
    if ! "${cmd2[@]}" 2>> "$fflog_file"
    then
        remux_failed="1"
    fi
fi

# Delete nosubs-file, if remux was successfull
if [[ "$remux_failed" == "0" ]]; then
    rm "$encoded_file"
fi

# Build Pushover notification
title="Video converted to H.264"
if [[ "$encoding_failed" == "1" ]]; then
    title="[E-FAILED] $title"
elif [[ "$remux_failed" == "1" ]]; then
    title="[R-FAILED] $title"
fi

message="<b>$(basename "${input_file%.*}")</b> <br>"
message+="size: ${encoded_size_gib}GiB / ${input_size_gib}GiB (${filesize_reduction_rate}) <br>"
message+="duration: ${encoded_duration} / ${input_duration} "

fflog_tail="$(tail -c 1000 "$fflog_file" | sed -E 's/^\[libx[^\]]+\] //; s/$/ <br>/')"
if [[ "$encoding_failed" == "1" || "$remux_failed" == "1" ]]; then
    message+="<br> <br>"
    message+="<b>Log</b> <i>failed: encoding=$encoding_failed remux=$remux_failed</i> <br>"
    message+="$fflog_tail"
fi

# use modified pushover-cli to support HTML messages
python3 /root/pushover-cli.py -d "script" "$message" "$title"
