"""FastAPI 入口。

- API 路由: /api/*
- 静态挂载: /files (处理结果, 支持 Range 供视频拖动), /uploads (原始上传)
- 若存在前端构建产物 ../frontend/dist 则同时托管
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import OUTPUTS, UPLOADS
from .routers import media, task

app = FastAPI(title="智能去水印平台 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(task.router)
app.include_router(media.router)

app.mount("/files", StaticFiles(directory=OUTPUTS), name="files")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/diag")
async def diag():
    """运行环境自检(只读): 用于排查部署环境下的视频编码问题。"""
    import os
    import shutil
    import subprocess
    import sys

    from .config import FFMPEG, VIDEO_ENCODER

    ver = ""
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-version"],
                           capture_output=True, text=True, timeout=15)
        ver = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else ""
    except Exception as e:  # noqa: BLE001
        ver = f"error: {e}"

    du = shutil.disk_usage(str(OUTPUTS))
    probe = OUTPUTS / ".diag_write"
    writable = True
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError:
        writable = False

    try:
        import imageio_ffmpeg

        imageio_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        imageio_bin = ""

    return {
        "python": sys.version.split()[0],
        "cpus": os.cpu_count(),
        "port": os.environ.get("PORT"),
        "ffmpeg": FFMPEG,
        "ffmpeg_version": ver,
        "video_encoder": VIDEO_ENCODER,
        "imageio_ffmpeg": imageio_bin,
        "storage_writable": writable,
        "disk_free_mb": round(du.free / 1024 / 1024),
    }


# 生产模式: 托管前端构建产物
# 本地开发走 ../frontend/dist; 发布包内静态资源放在 backend/static
_BACKEND = Path(__file__).resolve().parent.parent
_CANDIDATES = [
    _BACKEND.parent / "frontend" / "dist",
    _BACKEND / "static",
]
_dist = next((p for p in _CANDIDATES if p.is_dir()), None)
if _dist is not None:
    app.mount("/", StaticFiles(directory=_dist, html=True), name="spa")
