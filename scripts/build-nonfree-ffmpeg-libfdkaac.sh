# BUILD: fdk-aac codec
sudo apt update
sudo apt install -y autoconf automake build-essential libtool pkg-config git yasm nasm zlib1g-dev

# Get source
git clone https://github.com/mstorsjo/fdk-aac.git
cd fdk-aac

# Prepare build system
autoreconf -fiv

# Configure build (static library, suitable for ffmpeg)
./configure --prefix=/usr/local --disable-shared

# Compile and install
make -j$(nproc)
sudo make install

cd ..

# Verify
ls /usr/local/lib | grep fdk

# ----------

# BUILD: ffmpeg with non-free codecs
sudo apt update
sudo apt install -y libass-dev libdav1d-dev libx264-dev libx265-dev libmp3lame-dev libopus-dev libvpx-dev libvorbis-dev libxvidcore-dev libdav1d-dev

git clone https://github.com/FFmpeg/FFmpeg.git
cd FFmpeg

./configure \
  --prefix=/usr/local \
  #--pkg-config-flags="--static" \
  --extra-cflags="-I/usr/local/include" \
  --extra-ldflags="-L/usr/local/lib" \
  --extra-libs="-lpthread -lm" \
  --enable-gpl \
  --enable-nonfree \
  --enable-libfdk_aac \
  --enable-libx264 \
  --enable-libx265 \
  --enable-libmp3lame \
  --enable-libopus \
  --enable-libvpx \
  --enable-libass \
  --enable-libvorbis \
  --enable-libdav1d \
  --enable-libxvid

make -j$(nproc)
sudo make install
hash -r

# Verify
# expected: libfdk_aac      AAC (Advanced Audio Coding) (codec aac)
ffmpeg -encoders | grep fdk_aac
