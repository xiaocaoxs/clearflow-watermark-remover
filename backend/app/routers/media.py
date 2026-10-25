"""媒体访问 API：预览 / 下载。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import OUTPUTS, UPLOADS
from ..services import pipeline

router = APIRouter(prefix="/api", tags=["media"])


def _task_or_404(task_id: str):
    task = pipeline.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/task/{task_id}/original")
async def original_media(task_id: str):
    """原始文件下载/展示。"""
    task = _task_or_404(task_id)
    p = Path(task.input_path)
    if not p.exists():
        raise HTTPException(404, "原文件不存在")
    return FileResponse(p, media_type="application/octet-stream",
                        filename=f"original{task.input_ext}")


@router.get("/task/{task_id}/result")
async def result_media(task_id: str):
    """处理结果文件。"""
    task = _task_or_404(task_id)
    if not task.output_name:
        raise HTTPException(404, "结果尚未生成")
    p = OUTPUTS / task.output_name
    if not p.exists():
        raise HTTPException(404, "结果文件不存在")
    return FileResponse(p, media_type="application/octet-stream",
                        filename=f"no_watermark{task.input_ext if task.media_type == 'image' else '.mp4'}")


@router.get("/task/{task_id}/detect-preview")
async def detect_preview(task_id: str):
    """检测标注图(红框可视化)。"""
    task = _task_or_404(task_id)
    if not task.detect_preview:
        raise HTTPException(404, "暂无检测预览")
    p = OUTPUTS / task.detect_preview
    if not p.exists():
        raise HTTPException(404, "检测预览不存在")
    return FileResponse(p, media_type="image/jpeg")
