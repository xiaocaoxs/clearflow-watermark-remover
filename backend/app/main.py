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


# 生产模式: 托管前端构建产物
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="spa")
