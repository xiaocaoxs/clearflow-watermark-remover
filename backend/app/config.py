"""全局配置：路径、外部工具探测、上传限制。"""
from __future__ import annotations

import os
import shutil
import subprocess
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


def _ffmpeg_encoders(path: str) -> str:
    """取 ffmpeg 的编码器列表(失败返回空串)。"""
    try:
        r = subprocess.run([path, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout
    except Exception:  # noqa: BLE001
        return ""


def _pick_ffmpeg() -> str:
    """优先选支持 libx264 的 ffmpeg。

    容器/托管环境里常自带一个精简 ffmpeg，缺 libx264 会让视频编码直接失败，
    因此不能只按路径存在与否来选。
    """
    existing = [p for p in _FFMPEG_CANDIDATES if p and os.path.exists(p)]
    for p in existing:
        if "libx264" in _ffmpeg_encoders(p):
            return p
    # 系统 ffmpeg 都不带 libx264 → 回退 imageio-ffmpeg 静态二进制(自带完整编码器)
    try:
        import imageio_ffmpeg

        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:  # noqa: BLE001
        pass
    if existing:
        return existing[0]
    return "ffmpeg"


FFMPEG = _pick_ffmpeg()
_ENC = _ffmpeg_encoders(FFMPEG)
VIDEO_ENCODER = "libx264" if "libx264" in _ENC else "mpeg4"

_FFPROBE_CANDIDATES = [
    shutil.which("ffprobe") or "",
    "/opt/homebrew/bin/ffprobe",
    "/usr/local/bin/ffprobe",
    "/usr/bin/ffprobe",
]
FFPROBE = next((p for p in _FFPROBE_CANDIDATES if p and os.path.exists(p)), "ffprobe")
