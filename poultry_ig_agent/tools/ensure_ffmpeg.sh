#!/usr/bin/env bash
# ffmpeg + ffprobe даярдоо: (1) бар болсо — өткөрөт, (2) PyPI static-ffmpeg, (3) apt (акыркы жол, чек менен).
set -euo pipefail
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  echo "ffmpeg бар - $(ffmpeg -version | head -1)"; exit 0
fi
if timeout 240 pip install -q static-ffmpeg; then
  dir=""
  for try in 1 2 3; do   # жүктөө булагы убактылуу 5xx берсе (run 46050658908: 504) — кайра аракет; set -e скриптти токтотпосун
    dir=$(timeout 240 python -c "from static_ffmpeg import run; f,p=run.get_or_fetch_platform_executables_else_raise(); import os; print(os.path.dirname(f))" 2>&1 | tail -1) || dir=""
    [ -n "$dir" ] && [ -x "$dir/ffmpeg" ] && break
    echo "static-ffmpeg жүктөлгөн жок ($try-аракет)"; dir=""; sleep $((try * 10))
  done
  if [ -n "$dir" ] && [ -x "$dir/ffmpeg" ]; then
    echo "$dir" >> "${GITHUB_PATH:-/dev/null}"; export PATH="$dir:$PATH"
    echo "static-ffmpeg - $("$dir/ffmpeg" -version | head -1)"; exit 0
  fi
fi
echo "static-ffmpeg болбоду, apt менен аракет..."
timeout 300 sudo apt-get update -qq && timeout 300 sudo apt-get install -y -qq ffmpeg
