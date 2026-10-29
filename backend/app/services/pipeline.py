"""任务编排：上传/解析 → 检测 → 去除 → 产出成品与预览。"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ..config import UPLOADS, OUTPUTS, TEMP
from . import detector, remover, link_resolver


@dataclass
class Task:
    id: str
    media_type: str                    # image / video
    status: str = "uploaded"            # uploaded/detecting/processing/done/failed
    stage: str = ""
    progress: float = 0.0              # 0~1
    input_path: str = ""
    input_ext: str = ""
    output_name: str = ""
    detect_preview: str = ""            # 检测标注图文件名
    regions: list = field(default_factory=list)   # 图片: Region dicts
    tracks: list = field(default_factory=list)    # 视频: Track dicts
    meta: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.id,
            "media_type": self.media_type,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "regions": self.regions,
            "tracks": self.tracks,
            "meta": self.meta,
            "error": self.error,
            "has_result": bool(self.output_name) and self.status == "done",
            "input_name": Path(self.input_path).name if self.input_path else "",
            "output_name": self.output_name,
            "detect_preview": self.detect_preview,
        }


TASKS: dict[str, Task] = {}


def create_task(media_type: str, input_path: str, ext: str,
                source: str = "upload", meta: dict | None = None) -> Task:
    task = Task(id=uuid.uuid4().hex[:12], media_type=media_type,
                input_path=str(input_path), input_ext=ext, meta=meta or {})
    task.meta["source"] = source
    TASKS[task.id] = task
    return task


def get_task(task_id: str) -> Task | None:
    return TASKS.get(task_id)


def start_processing(task_id: str) -> bool:
    task = TASKS.get(task_id)
    if not task or task.status in ("detecting", "processing", "done"):
        return False
    threading.Thread(target=_run, args=(task,), daemon=True).start()
    return True


def _run(task: Task):
    try:
        if task.media_type == "video":
            _process_video(task)
        else:
            _process_image(task)
    except Exception as e:  # noqa: BLE001
        task.status = "failed"
        task.error = f"{e}"
        traceback.print_exc()


# ---------------- 图片管线 ----------------

def _process_image(task: Task):
    task.status, task.stage = "detecting", "正在检测水印区域"
    task.progress = 0.15

    img = cv2.imread(task.input_path)
    if img is None:
        raise RuntimeError("图片读取失败")
    regions = detector.detect_regions(img, white_text=True)
    task.regions = [r.to_dict() for r in regions]

    # 检测标注预览
    vis = detector.draw_regions(img, regions)
    preview_name = f"{task.id}_detect.jpg"
    cv2.imwrite(str(OUTPUTS / preview_name), vis,
                [cv2.IMWRITE_JPEG_QUALITY, 92])
    task.detect_preview = preview_name

    task.status, task.stage = "processing", "正在修复图片水印"
    task.progress = 0.5

    out_name = f"{task.id}_clean{task.input_ext}"
    out_path = OUTPUTS / out_name
    ok = remover.remove_image(task.input_path, str(out_path), regions)
    if not ok:
        raise RuntimeError("图片处理失败")

    task.output_name = out_name
    task.meta.update({
        "detected_count": len(regions),
        "watermark_found": bool(regions),
    })
    task.status, task.stage, task.progress = "done", "完成", 1.0


# ---------------- 视频管线 ----------------

def _process_video(task: Task):
    task.status, task.stage = "detecting", "读取视频信息"
    task.progress = 0.05
    info = remover.probe_media(task.input_path)
    duration = info["duration"] or 0
    task.meta.update({
        "width": info["width"], "height": info["height"],
        "duration": round(duration, 2),
    })
    if duration <= 0:
        raise RuntimeError("无法读取视频时长")

    # 采样策略: 时长短步长密, 上限 96 帧(加密采样以稳定跟踪移动水印)
    n = min(96, max(16, int(duration / 0.4)))
    step = duration / n
    samples = []
    frames_gray = []
    overlay_masks = []
    cap = cv2.VideoCapture(task.input_path)
    use_cv2 = cap.isOpened()
    frame_path = TEMP / f"{task.id}_frame.jpg"
    for i in range(n):
        t = min(duration - 0.05, i * step)
        frame = None
        if use_cv2:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, f = cap.read()
            if ok:
                frame = f
        if frame is None:
            if remover.extract_frame(task.input_path, t, str(frame_path)):
                frame = cv2.imread(str(frame_path))
        if frame is None:
            continue
        regions = detector.detect_regions(frame, white_text=True)
        samples.append((t, regions))
        frames_gray.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        overlay_masks.append(detector.local_contrast_mask(frame))
        task.stage = f"正在检测水印 ({i + 1}/{n})"
        task.progress = 0.05 + 0.55 * (i + 1) / n
    if use_cv2:
        cap.release()
    frame_path.unlink(missing_ok=True)

    tracks = detector.build_tracks(samples, min_hits=detector.VIDEO_MIN_HITS,
                                   frames_gray=frames_gray)
    # 补漏: 白字压在明亮背景上时逐帧检测拿不到, 用跨帧累积的静态叠加层补齐
    overlay_tracks = detector.build_overlay_tracks(
        overlay_masks, [t for t, _ in samples])
    if overlay_tracks:
        tracks = detector.merge_track_sets(tracks, overlay_tracks)
    tracks = detector.filter_bottom_tracks(tracks, info["height"])
    task.tracks = [{
        "x1": tr.x1, "y1": tr.y1, "x2": tr.x2, "y2": tr.y2,
        "t0": round(tr.t0, 2), "t1": round(tr.t1, 2), "hits": tr.hits,
    } for tr in tracks]

    # 检测标注预览: 画最终轨迹在该时刻的激活框, 与逐帧修复范围保持一致
    task.stage = "生成检测预览"
    mid_t = duration / 2
    preview_frame = TEMP / f"{task.id}_mid.jpg"
    if remover.extract_frame(task.input_path, mid_t, str(preview_frame)):
        frame = cv2.imread(str(preview_frame))
        if frame is not None:
            active = [detector.Region(x=tr.x1, y=tr.y1, w=tr.w, h=tr.h)
                      for tr in tracks if tr.t0 <= mid_t <= tr.t1]
            vis = detector.draw_regions(frame, active)
            task.detect_preview = f"{task.id}_detect.jpg"
            cv2.imwrite(str(OUTPUTS / task.detect_preview), vis,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
        preview_frame.unlink(missing_ok=True)

    task.status, task.stage = "processing", "正在逐帧修复视频水印(高保真)"
    task.progress = 0.65

    out_name = f"{task.id}_clean.mp4"
    out_path = OUTPUTS / out_name

    def on_progress(p: float):
        task.progress = 0.65 + 0.35 * p
        task.stage = f"视频处理中 {int(p * 100)}%"

    ok = remover.remove_video(task.input_path, str(out_path), tracks,
                              duration, info["has_audio"],
                              info["audio_codec"], step=step,
                              on_progress=on_progress)
    if not ok:
        raise RuntimeError("视频处理失败")

    task.output_name = out_name
    task.meta.update({
        "detected_tracks": len(tracks),
        "watermark_found": bool(tracks),
    })
    task.status, task.stage, task.progress = "done", "完成", 1.0


# ---------------- 链接解析管线 ----------------

async def resolve_and_download(url: str) -> Task:
    """解析分享链接并代理下载媒体 → 创建任务。"""
    result = await link_resolver.parse_link(url)
    platform = result["platform"]
    media_type = result["media_type"]   # image / video
    media_url = result["url"]

    ext = ".mp4" if media_type == "video" else ".jpg"
    if "?" in media_url or "." in media_url.split("/")[-1]:
        tail = media_url.split("?")[0].split("/")[-1]
        for cand in (".mp4", ".mov", ".m4v", ".webm"):
            if tail.lower().endswith(cand):
                ext, media_type = cand, "video"
                break
        else:
            for cand in (".jpg", ".jpeg", ".png", ".webp"):
                if tail.lower().endswith(cand):
                    ext, media_type = cand, "image"
                    break

    task_id = uuid.uuid4().hex[:12]
    dest = UPLOADS / f"{task_id}{ext}"
    referer_map = {
        "xiaohongshu": "https://www.xiaohongshu.com/",
        "douyin": "https://www.douyin.com/",
        "tiktok": "https://www.tiktok.com/",
    }
    await link_resolver.download_media(media_url, dest,
                                        referer_map.get(platform, ""))

    task = create_task(media_type, str(dest), ext, source="link",
                       meta={"platform": platform,
                             "title": result.get("title", "")})
    task.id = task_id
    TASKS[task_id] = task
    return task
