"""全局配置：路径、外部工具探测、上传限制。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
STORAGE = BASE_DIR / "storage"
UPLOADS = STORAGE / "uploads"
OUTPUTS = STORAGE / "outputs"
TEMP = STORAGE / "temp"

for _d in (UPLOADS, OUTPUTS, TEMP):
    _d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = 200 * 1024 * 1024  # 200MB

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi"}

# 测试数据目录
TEST_DIR = BASE_DIR.parent / "test"

_FFMPEG_CANDIDATES = [
    shutil.which("ffmpeg") or "",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]
FFMPEG = next((p for p in _FFMPEG_CANDIDATES if p and os.path.exists(p)), "")
if not FFMPEG:
    # 回退: imageio-ffmpeg 自带的静态二进制(含 delogo 滤镜)
    try:
        import imageio_ffmpeg

        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG = "ffmpeg"

_FFPROBE_CANDIDATES = [
    shutil.which("ffprobe") or "",
    "/opt/homebrew/bin/ffprobe",
    "/usr/local/bin/ffprobe",
    "/usr/bin/ffprobe",
]
FFPROBE = next((p for p in _FFPROBE_CANDIDATES if p and os.path.exists(p)), "ffprobe")
