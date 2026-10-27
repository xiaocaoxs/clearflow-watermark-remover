"""水印去除模块。

图片: cv2.inpaint (Telea 快速行进法)
视频: 逐帧 cv2.inpaint(Telea) 修复 —— Telea 沿等照度线传播、保留纹理方向，
      相比 delogo 的双线性插值修复质量显著更好；
      编码 CRF16 高保真(非水印区视觉无损)，音频流无损直拷。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np

from ..config import FFMPEG

# 逐帧修复参数
REPAIR_PAD = 2        # 检测框外扩像素；过大会把正常纹理带入修复区
REPAIR_MARGIN = 24    # inpaint ROI 额外上下文边距(供 Telea 取边界信息)
REPAIR_RADIUS = 3     # 小半径减少纹理被扩散成模糊块
ENCODER_CRF = "16"    # 高保真(视觉无损)
ENCODER_PRESET = "medium"

# 形状 mask 提取参数(只修复水印实际形状, 保留背景纹理)
SHAPE_BRIGHT_TH = 185    # 白字亮度阈值
SHAPE_WHITE_V = 110      # 低饱和白字: 亮度下限(半透明白字)
SHAPE_WHITE_S = 90       # 低饱和白字: 饱和度上限
SHAPE_COLOR_S = 70       # 彩色 logo: 饱和度下限
SHAPE_COLOR_V = 130      # 彩色 logo: 亮度下限
SHAPE_COVER_MAX = 0.42   # 覆盖率过高通常表示把明亮背景误当成了水印
SHAPE_COVER_MIN = 0.003  # 覆盖率过低时不冒险整框修复
LOCAL_CONTRAST_MIN = 6   # 半透明白字相对局部背景的最小亮度差
COMPACT_AREA = 0.08      # 小于该占比时把笔画撑开修复；再大就只涂细笔画，避免误伤画面


def probe_media(path: str) -> dict:
    """读取媒体元信息: cv2 取宽高/时长 + ffmpeg stderr 解析音频流。"""
    cap = cv2.VideoCapture(path)
    ok = cap.isOpened()
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if ok else 0
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if ok else 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()

    duration = frames / fps if fps > 0 else 0.0
    has_audio, audio_codec = False, ""
    try:
        r = subprocess.run([FFMPEG, "-i", path], capture_output=True,
                           text=True, timeout=30)
        m = re.search(r"Audio: (\w+)", r.stderr)
        if m:
            has_audio, audio_codec = True, m.group(1)
        if duration <= 0:
            m2 = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", r.stderr)
            if m2:
                h_, m_, s_ = m2.groups()
                duration = int(h_) * 3600 + int(m_) * 60 + float(s_)
    except Exception:  # noqa: BLE001
        pass

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "has_audio": has_audio,
        "audio_codec": audio_codec,
        "size": 0,
    }


def extract_frame(path: str, t: float, out_path: str) -> bool:
    """提取视频 t 秒处的一帧。"""
    cmd = [FFMPEG, "-y", "-ss", f"{t:.3f}", "-i", path,
           "-frames:v", "1", "-q:v", "2", out_path]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


def _coverage(mask: np.ndarray, inner: np.ndarray) -> float:
    return float(np.count_nonzero(mask)) / max(1, float(np.count_nonzero(inner)))


def _extract_shape(roi: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """提取水印笔画 mask，异常时返回空 mask 以保护原始纹理。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 低频背景估计可区分半透明亮字与本来就很亮的平坦背景。
    local_bg = cv2.GaussianBlur(gray, (0, 0), 3.0)
    contrast = cv2.subtract(gray, local_bg)
    bright = np.where((gray > SHAPE_BRIGHT_TH) &
                      (contrast >= LOCAL_CONTRAST_MIN), 255, 0).astype(np.uint8)
    whiteish = np.where((hsv[..., 2] > SHAPE_WHITE_V) &
                        (hsv[..., 1] < SHAPE_WHITE_S) &
                        (contrast >= LOCAL_CONTRAST_MIN), 255, 0).astype(np.uint8)
    colorful = np.where((hsv[..., 1] > SHAPE_COLOR_S) &
                        (hsv[..., 2] > SHAPE_COLOR_V), 255, 0).astype(np.uint8)

    col_cov = _coverage(cv2.bitwise_and(colorful, inner), inner)
    candidates = cv2.bitwise_or(bright, whiteish)
    if col_cov <= 0.12:
        candidates = cv2.bitwise_or(candidates, colorful)
    shape = cv2.bitwise_and(candidates, inner)

    # 3x3 闭运算连接断裂笔画，仅膨胀一圈覆盖文字抗锯齿边缘。
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    shape = cv2.morphologyEx(shape, cv2.MORPH_CLOSE, k)
    shape = cv2.dilate(shape, k, iterations=1)

    cov = _coverage(shape, inner)
    if cov < SHAPE_COVER_MIN or cov > SHAPE_COVER_MAX:
        return np.zeros_like(inner)
    return shape


def _repair_frame_region(frame: np.ndarray, x1: int, y1: int,
                         x2: int, y2: int,
                         radius: int = REPAIR_RADIUS) -> None:
    """修复水印。紧凑角标整框涂掉；更大的区域只涂笔画，避免误伤画面。"""
    H, W = frame.shape[:2]
    rx1, ry1 = max(0, x1 - REPAIR_MARGIN), max(0, y1 - REPAIR_MARGIN)
    rx2, ry2 = min(W, x2 + REPAIR_MARGIN), min(H, y2 + REPAIR_MARGIN)
    if rx2 - rx1 < 4 or ry2 - ry1 < 4:
        return
    roi = frame[ry1:ry2, rx1:rx2]
    inner = np.zeros(roi.shape[:2], np.uint8)
    inner[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1] = 255
    shape = _extract_shape(roi, inner)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    inside = gray[inner > 0]
    bright_frac = float((inside > 200).mean()) if inside.size else 0.0
    # 紧凑角标把笔画撑开，或对实心白底整框修复。大块区域仍只涂笔画。
    box_area = max(1, (x2 - x1) * (y2 - y1))
    compact = box_area <= COMPACT_AREA * H * W
    ink = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    if compact and bright_frac > 0.28:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.dilate(inner, kernel, iterations=2)
    elif compact and _coverage(shape, inner) >= 0.12:
        mask = cv2.dilate(shape, ink, iterations=3)
        mask = cv2.bitwise_and(mask, inner)
    elif np.any(shape):
        mask = shape
    else:
        return

    repaired = cv2.inpaint(roi, mask, max(1, int(radius)), cv2.INPAINT_TELEA)
    roi[mask > 0] = repaired[mask > 0]


def remove_image(src: str, dst: str, regions,
                 radius: int = REPAIR_RADIUS) -> bool:
    """图片去水印：形状 mask inpaint 修复(保留背景纹理)。"""
    img = cv2.imread(src, cv2.IMREAD_COLOR)
    if img is None:
        return False
    if not regions:
        cv2.imwrite(dst, img)
        return True
    H, W = img.shape[:2]
    for r in regions:
        x1, y1 = max(0, r.x - 2), max(0, r.y - 2)
        x2, y2 = min(W, r.x2 + 2), min(H, r.y2 + 2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        _repair_frame_region(img, x1, y1, x2, y2, radius=radius)
    return cv2.imwrite(dst, img)


def remove_video(src: str, dst: str, tracks, duration: float,
                 has_audio: bool, audio_codec: str = "",
                 step: float = 1.0, on_progress=None) -> bool:
    """视频去水印：逐帧 Telea inpaint + CRF16 高保真编码 + 音频直拷。

    流程:
      1) OpenCV 逐帧解码 → 对当前时刻激活的轨迹 ROI 做 cv2.inpaint →
         rawvideo 管道送 ffmpeg (libx264 CRF16) 输出静音视频
      2) 无损混流原始音频流(直拷)，容器不兼容时 AAC 兜底
    """
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        return False
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 1.0 or fps > 240.0:
        fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int(duration * fps)
    if W == 0 or H == 0:
        cap.release()
        return False

    # 轨迹 → (t0, t1, x1, y1, x2, y2)；时间两端各扩一个采样步长
    acts = []
    for tr in tracks:
        t0 = max(0.0, tr.t0 - step * 0.98)
        t1 = min(duration, tr.t1 + step * 0.98)
        if t1 <= t0:
            continue
        x1, y1 = max(0, tr.x1 - REPAIR_PAD), max(0, tr.y1 - REPAIR_PAD)
        x2, y2 = min(W, tr.x2 + REPAIR_PAD), min(H, tr.y2 + REPAIR_PAD)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        acts.append((t0, t1, x1, y1, x2, y2))

    if not acts:
        cap.release()
        cmd = [FFMPEG, "-y", "-i", src, "-c", "copy", "-movflags",
               "+faststart", dst]
        return _run_ffmpeg(cmd, duration, on_progress)

    # ---- 第一步: 逐帧修复视频流 ----
    tmp = str(Path(dst).with_name(Path(dst).stem + ".tmp.mp4"))
    cmd = [FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", f"{fps:.6f}", "-i", "pipe:0",
           "-c:v", "libx264", "-crf", ENCODER_CRF,
           "-preset", ENCODER_PRESET, "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t = idx / fps
            for (t0, t1, x1, y1, x2, y2) in acts:
                if t < t0 or t > t1:
                    continue
                _repair_frame_region(frame, x1, y1, x2, y2)
            proc.stdin.write(frame.tobytes())
            idx += 1
            if on_progress and total > 0 and idx % 20 == 0:
                on_progress(min(0.99, idx / total))
    except BrokenPipeError:
        pass
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
    if proc.wait() != 0:
        _safe_unlink(tmp)
        raise RuntimeError("ffmpeg 视频编码失败")
    if idx == 0:
        _safe_unlink(tmp)
        return False

    # ---- 第二步: 无损混流原始音频 ----
    if not has_audio:
        os.replace(tmp, dst)
        if on_progress:
            on_progress(1.0)
        return True

    try:
        cmd = [FFMPEG, "-y", "-i", tmp, "-i", src,
               "-map", "0:v:0", "-map", "1:a:0?",
               "-c:v", "copy", "-c:a", "copy",
               "-movflags", "+faststart", dst]
        ok = _run_ffmpeg(cmd, duration)
    except RuntimeError:
        ok = False
    if not ok:
        # 音频直拷容器不兼容 → AAC 转码兜底
        try:
            cmd = [FFMPEG, "-y", "-i", tmp, "-i", src,
                   "-map", "0:v:0", "-map", "1:a:0?",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", dst]
            ok = _run_ffmpeg(cmd, duration)
        except RuntimeError:
            ok = False
    _safe_unlink(tmp)
    if on_progress:
        on_progress(1.0)
    return ok


def _safe_unlink(path: str):
    try:
        os.unlink(path)
    except OSError:
        pass


def _run_ffmpeg(cmd, duration: float, on_progress=None) -> bool:
    """运行 ffmpeg 并解析 -progress 输出回调进度。"""
    cmd = cmd + ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                us = int(line.split("=")[1])
                cur = us / 1_000_000
                if on_progress and duration > 0:
                    on_progress(min(0.99, cur / duration))
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg 失败: {err[-500:]}")
    if on_progress:
        on_progress(1.0)
    return proc.returncode == 0
