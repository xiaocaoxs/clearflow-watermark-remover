"""任务相关 API：上传 / 链接解析 / 触发处理 / 状态查询。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import (ALLOWED_IMAGE_EXT, ALLOWED_VIDEO_EXT,
                      MAX_UPLOAD_SIZE, UPLOADS)
from ..services import pipeline
from ..services.link_resolver import ResolverError

router = APIRouter(prefix="/api", tags=["task"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...),
                      media_type: str = Form("auto")):
    """本地文件上传。media_type: image|video|auto(按扩展名判断)。"""
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() \
        if "." in (file.filename or "") else ""
    if ext in ALLOWED_VIDEO_EXT:
        mtype = "video"
    elif ext in ALLOWED_IMAGE_EXT:
        mtype = "image"
    else:
        raise HTTPException(400, f"不支持的文件类型: {ext or '未知'}")
    if media_type in ("image", "video"):
        mtype = media_type

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "文件超过 200MB 限制")
    if not data:
        raise HTTPException(400, "空文件")

    task = pipeline.create_task(mtype, "", ext, source="upload",
                                meta={"filename": file.filename or "file"})
    dest = UPLOADS / f"{task.id}{ext}"
    dest.write_bytes(data)
    task.input_path = str(dest)
    return {"task_id": task.id, "media_type": mtype}


@router.post("/parse-link")
async def parse_link(body: dict):
    """解析分享链接(小红书/抖音/TikTok)并下载。"""
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "链接不能为空")
    try:
        task = await pipeline.resolve_and_download(url)
    except ResolverError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"链接解析失败: {e}")
    return {
        "task_id": task.id,
        "media_type": task.media_type,
        "platform": task.meta.get("platform"),
        "title": task.meta.get("title", ""),
    }


@router.post("/process")
async def process(body: dict):
    """触发水印检测+去除(异步执行, 用 /task 轮询)。"""
    task_id = body.get("task_id") or ""
    task = pipeline.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not task.input_path:
        raise HTTPException(400, "任务缺少输入文件")
    if not pipeline.start_processing(task_id):
        raise HTTPException(409, "任务已在处理中或已完成")
    return {"task_id": task_id}


@router.get("/task/{task_id}")
async def task_status(task_id: str):
    task = pipeline.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task.to_dict()
