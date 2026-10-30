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

from ..config import FFMPEG, VIDEO_ENCODER

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
COMPACT_AREA = 0.08      # 仅在小区域内尝试识别封闭的实心底牌

# 彩色水印(如 TikTok 青/粉渐变 logo): 用 LAB 色度相对背景中位数的偏差判定。
# 比 HSV 饱和度阈值稳，暖色背景不会被整片当成彩色水印。
CHROMA_DEV_TH = 14

# 误检过滤: 水印是叠加在画面上的"亮层"，其笔画像素明显亮于背景；
# 而误检到背景结构(竹竿/墙沿/腿部高光)时，所谓笔画就是背景本身，亮度相当。
# 实测: 真水印「候选亮度-背景亮度」+75~+240，误检 -7~+37。
TRACK_MIN_BRIGHT_DELTA = 60
# 兜底: 大面积叠加层即使对比弱也认为是真水印(如白字压白底)
TRACK_BIG_COVER = 0.15

# 深色底牌(墨迹/黑底 logo): 白字压在黑底上时只修复白字会留下黑色残影
DARK_PLATE_DELTA = 45    # 相对周边背景中位数的亮度落差下限
DARK_PLATE_MAX_TH = 90   # 绝对亮度上限: 高于此值不算"黑底"
DARK_PLATE_MIN_COVER = 0.15  # 底牌占检测框面积下限
DARK_PLATE_MAX_COVER = 0.90  # 上限: 超过说明整块都是暗部而非底牌
RESIDUAL_DIFF = 16       # 残差扩张阈值: 与重建背景的最大通道差


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


def _dark_plate(gray: np.ndarray, inner: np.ndarray,
                strokes: np.ndarray) -> np.ndarray | None:
    """提取 logo 的深色底牌(墨迹/黑底)。

    白字水印常压在黑色墨迹或黑底 logo 上，只修复白字笔画会把底牌留成
    一块黑斑。判据是「显著暗于周边背景」+「与白字笔画相连」+「面积可观」，
    三者同时满足才纳入修复，避免把画面里的深色内容误当底牌。
    """
    outside = gray[inner == 0]
    if outside.size == 0:
        return None
    bg = float(np.median(outside))
    th = min(DARK_PLATE_MAX_TH, bg - DARK_PLATE_DELTA)
    dark = np.where((gray < th) & (inner > 0), 255, 0).astype(np.uint8)
    if not np.any(dark):
        return None

    inner_area = max(1, int(np.count_nonzero(inner)))
    reach = (cv2.dilate(strokes, np.ones((9, 9), np.uint8))
             if np.any(strokes) else inner)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    plate = np.zeros_like(dark)
    for i in range(1, stats.shape[0]):
        if stats[i, cv2.CC_STAT_AREA] < DARK_PLATE_MIN_COVER * inner_area:
            continue
        if not np.any(reach[labels == i]):
            continue
        plate[labels == i] = 255
    if not np.any(plate):
        return None
    if float(np.count_nonzero(plate)) / inner_area > DARK_PLATE_MAX_COVER:
        return None
    # 闭运算补上白字笔画在底牌上留下的孔洞，整块一起修复
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    plate = cv2.morphologyEx(plate, cv2.MORPH_CLOSE, k)
    return cv2.bitwise_and(plate, inner)


def _stroke_candidates(roi: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """提取"疑似叠加笔画"候选像素(残差扩张与形态学之前)。

    判据: 明显亮于局部背景、低饱和白字、或色度明显偏离背景中位色。
    与框边界相连的连通域会被剔除 —— 叠加层水印通常完整落在框内，
    而背景结构(竹竿/墙沿/地平线)会越过检测框。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 低频背景估计可区分半透明亮字与本来就很亮的平坦背景。
    local_bg = cv2.GaussianBlur(gray, (0, 0), 3.0)
    contrast = cv2.subtract(gray, local_bg)
    outside_contrast = contrast[inner == 0]
    contrast_min = LOCAL_CONTRAST_MIN
    if outside_contrast.size:
        contrast_min = max(contrast_min, min(20.0, float(np.percentile(outside_contrast, 99)) + 3))
    bright = np.where((gray > SHAPE_BRIGHT_TH) &
                      (contrast >= contrast_min), 255, 0).astype(np.uint8)
    whiteish = np.where((hsv[..., 2] > SHAPE_WHITE_V) &
                        (hsv[..., 1] < SHAPE_WHITE_S) &
                        (contrast >= contrast_min), 255, 0).astype(np.uint8)

    # 彩色水印: 相对背景中位色度的偏差, 而不是绝对饱和度
    # (暖色/木纹背景饱和度高, 用绝对阈值会把整片背景判成彩色水印)
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    a_ch = lab[..., 1].astype(np.int16)
    b_ch = lab[..., 2].astype(np.int16)
    outside_px = inner == 0
    if np.any(outside_px):
        a_bg = float(np.median(a_ch[outside_px]))
        b_bg = float(np.median(b_ch[outside_px]))
    else:
        a_bg, b_bg = float(np.median(a_ch)), float(np.median(b_ch))
    chroma_dev = np.maximum(np.abs(a_ch - a_bg), np.abs(b_ch - b_bg))
    colorful = np.where((chroma_dev > CHROMA_DEV_TH) & (inner > 0),
                        255, 0).astype(np.uint8)

    col_cov = _coverage(colorful, inner)
    candidates = cv2.bitwise_or(bright, whiteish)
    if col_cov <= 0.12:
        candidates = cv2.bitwise_or(candidates, colorful)
    _, labels = cv2.connectedComponents(candidates)
    crossing = np.unique(labels[inner == 0])
    candidates[np.isin(labels, crossing[crossing != 0])] = 0
    return cv2.bitwise_and(candidates, inner)


def _extract_shape(roi: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """提取水印笔画 mask，异常时返回空 mask 以保护原始纹理。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    shape = _stroke_candidates(roi, inner)

    # 残差扩张: 用当前掩码重建背景，把仍与重建背景明显不同的像素补进来。
    # 这些是 logo 的描边色差偏移、半透明软边 —— 留在掩码外会成为 Telea 的
    # 边界填充源，把描边颜色往里扩散成彩色鬼影。只接受紧贴笔画的残差，
    # 避免把框内的画面内容也吞进来。
    if np.any(shape):
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        for _ in range(2):
            bg_est = cv2.inpaint(roi, cv2.dilate(shape, k5), 5, cv2.INPAINT_TELEA)
            diff = np.abs(roi.astype(np.int16) - bg_est.astype(np.int16)).max(axis=2)
            extra = np.where((diff > RESIDUAL_DIFF) & (inner > 0),
                             255, 0).astype(np.uint8)
            near = cv2.dilate(shape, np.ones((15, 15), np.uint8))
            grown = cv2.bitwise_or(shape, cv2.bitwise_and(extra, near))
            if np.array_equal(grown, shape):
                break
            shape = grown

    # 3x3 闭运算连接断裂笔画，仅膨胀一圈覆盖文字抗锯齿边缘。
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    shape = cv2.morphologyEx(shape, cv2.MORPH_CLOSE, k)
    shape = cv2.dilate(shape, k, iterations=1)
    shape = cv2.bitwise_and(shape, inner)

    plate = _dark_plate(gray, inner, shape)
    if plate is not None:
        # 有深色底牌时以底牌为准: 只抹白字会在原位留一块黑斑
        return cv2.bitwise_or(shape, plate)

    cov = _coverage(shape, inner)
    if cov < SHAPE_COVER_MIN or cov > SHAPE_COVER_MAX:
        return np.zeros_like(inner)
    return shape


def _place_hint(hint, rx1: int, ry1: int, inner: np.ndarray) -> np.ndarray:
    """把相对轨迹框的笔画掩码对齐到 ROI 坐标系(rx1,ry1 为 ROI 左上角)。"""
    hx1, hy1, hm = hint
    if hm is None or hm.size == 0:
        return np.zeros_like(inner)
    ox, oy = hx1 - rx1, hy1 - ry1
    hh, hw = hm.shape[:2]
    sx, sy = max(0, -ox), max(0, -oy)
    dx, dy = max(0, ox), max(0, oy)
    ww = min(hw - sx, inner.shape[1] - dx)
    hh2 = min(hh - sy, inner.shape[0] - dy)
    out = np.zeros_like(inner)
    if ww > 0 and hh2 > 0:
        out[dy:dy + hh2, dx:dx + ww] = hm[sy:sy + hh2, sx:sx + ww]
    return out


def _roi_and_mask(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int):
    """按 REPAIR_MARGIN 取 ROI 与框内掩码区。"""
    H, W = frame.shape[:2]
    rx1, ry1 = max(0, x1 - REPAIR_MARGIN), max(0, y1 - REPAIR_MARGIN)
    rx2, ry2 = min(W, x2 + REPAIR_MARGIN), min(H, y2 + REPAIR_MARGIN)
    if rx2 - rx1 < 8 or ry2 - ry1 < 8:
        return None, None
    roi = frame[ry1:ry2, rx1:rx2]
    inner = np.zeros(roi.shape[:2], np.uint8)
    inner[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1] = 255
    return roi, inner


def region_overlay_stats(frame: np.ndarray, x1: int, y1: int,
                         x2: int, y2: int) -> tuple[float, float]:
    """区域叠加特征: (笔画覆盖率, 笔画亮度相对背景的差值)。

    真水印是比背景更亮的叠加层，差值大；误检到背景结构时差值接近 0。
    """
    roi, inner = _roi_and_mask(frame, x1, y1, x2, y2)
    if roi is None:
        return 1.0, 255.0  # 取不到区域时不做否定判断, 交给原有流程
    cand = _stroke_candidates(roi, inner)
    box_area = max(1, (x2 - x1) * (y2 - y1))
    cov = float(np.count_nonzero(cand)) / box_area

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    sel = cand > 0
    if not np.any(sel) or not np.any(inner == 0):
        return cov, 0.0
    fg = float(np.median(gray[sel]))
    bg = float(np.median(gray[inner == 0]))
    return cov, fg - bg


def region_overlay_coverage(frame: np.ndarray, x1: int, y1: int,
                            x2: int, y2: int) -> float:
    """区域内"疑似叠加笔画"占检测框的比例。"""
    return region_overlay_stats(frame, x1, y1, x2, y2)[0]


def region_is_background(frame: np.ndarray, x1: int, y1: int,
                         x2: int, y2: int) -> bool:
    """该区域是否更像背景结构(而非水印)。用于过滤误检，避免抹掉画面内容。"""
    cov, delta = region_overlay_stats(frame, x1, y1, x2, y2)
    return not (delta >= TRACK_MIN_BRIGHT_DELTA or cov >= TRACK_BIG_COVER)


def track_is_background(path: str, x1: int, y1: int, x2: int, y2: int,
                        times) -> bool:
    """在轨迹的若干时刻抽帧，判断该轨迹是否其实是背景结构。

    取多时刻的最优证据: 真水印只要在任一时刻呈现"明显亮于背景"的叠加就算成立，
    避免被个别低对比度帧误杀。
    """
    if not times:
        return False
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return False
    best_delta, best_cov = -255.0, 0.0
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t)) * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            cov, delta = region_overlay_stats(frame, x1, y1, x2, y2)
            best_delta = max(best_delta, delta)
            best_cov = max(best_cov, cov)
    finally:
        cap.release()
    return not (best_delta >= TRACK_MIN_BRIGHT_DELTA or best_cov >= TRACK_BIG_COVER)


def _repair_frame_region(frame: np.ndarray, x1: int, y1: int,
                         x2: int, y2: int,
                         radius: int = REPAIR_RADIUS,
                         mask_hint=None) -> None:
    """按笔画修复；有封闭边界且明显亮于周边的底牌按轮廓修复。

    mask_hint: (x1, y1, mask) —— 检测阶段跨帧累积的笔画掩码。
    低对比度帧(白字压白底)单帧抠不出形状时用它兜底，否则水印会整帧漏修。
    """
    H, W = frame.shape[:2]
    rx1, ry1 = max(0, x1 - REPAIR_MARGIN), max(0, y1 - REPAIR_MARGIN)
    rx2, ry2 = min(W, x2 + REPAIR_MARGIN), min(H, y2 + REPAIR_MARGIN)
    if rx2 - rx1 < 4 or ry2 - ry1 < 4:
        return
    roi = frame[ry1:ry2, rx1:rx2]
    inner = np.zeros(roi.shape[:2], np.uint8)
    inner[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1] = 255
    box_area = max(1, (x2 - x1) * (y2 - y1))
    compact = box_area <= COMPACT_AREA * H * W
    shape = _extract_shape(roi, inner)
    if mask_hint is not None:
        # 静态水印的笔画位置跨帧固定, 累积掩码比单帧抠图更完整(白字压白底时
        # 单帧只能抠到带黑边的部分)。单帧结果只在累积掩码邻域内补充细节,
        # 防止单帧误检把远处背景块也带进来。
        hint = _place_hint(mask_hint, rx1, ry1, inner)
        if np.any(hint):
            near = cv2.dilate(hint, np.ones((5, 5), np.uint8))
            shape = cv2.bitwise_or(hint, cv2.bitwise_and(shape, near))
            shape = cv2.dilate(shape, np.ones((5, 5), np.uint8))
            shape = cv2.bitwise_and(shape, inner)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    mask = shape
    if compact:
        outside = gray[inner == 0]
        if outside.size:
            threshold = max(200.0, float(np.median(outside)) + 35.0)
            bright = np.where((gray > threshold) & (inner > 0), 255, 0).astype(np.uint8)
            contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            badge = np.zeros_like(inner)
            for contour in contours:
                bx, by, bw, bh = cv2.boundingRect(contour)
                area = cv2.contourArea(contour)
                if area < box_area * 0.28 or area < bw * bh * 0.75:
                    continue
                # 开放到 ROI 边缘的亮区没有可确认的底牌轮廓。
                if bx == 0 or by == 0 or bx + bw >= gray.shape[1] or by + bh >= gray.shape[0]:
                    continue
                boundary = np.zeros_like(inner)
                cv2.drawContours(boundary, [contour], -1, 255, 1)
                ring = cv2.dilate(boundary, np.ones((3, 3), np.uint8))
                if np.any((ring > 0) & (inner == 0)):
                    continue
                cv2.drawContours(badge, [contour], -1, 255, cv2.FILLED)
            if np.any(badge):
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                badge = cv2.bitwise_and(cv2.dilate(badge, kernel), inner)
                mask = cv2.bitwise_or(mask, badge)
    if not np.any(mask):
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
        # 误检到实心背景结构(柱子/墙沿)时宁可不修，也不要抹掉画面内容
        if region_is_background(img, x1, y1, x2, y2):
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
        hint = ((tr.x1, tr.y1, tr.mask)
                if getattr(tr, "mask", None) is not None else None)
        acts.append((t0, t1, x1, y1, x2, y2, hint))

    if not acts:
        cap.release()
        cmd = [FFMPEG, "-y", "-i", src, "-c", "copy", "-movflags",
               "+faststart", dst]
        return _run_ffmpeg(cmd, duration, on_progress)

    # ---- 第一步: 逐帧修复视频流 ----
    tmp = str(Path(dst).with_name(Path(dst).stem + ".tmp.mp4"))
    if VIDEO_ENCODER == "libx264":
        enc_args = ["-c:v", "libx264", "-crf", ENCODER_CRF,
                    "-preset", ENCODER_PRESET]
    else:
        # 缺 libx264 的精简 ffmpeg: mpeg4 内置编码器兜底
        enc_args = ["-c:v", "mpeg4", "-q:v", "2"]
    cmd = [FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", f"{fps:.6f}", "-i", "pipe:0",
           *enc_args, "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", tmp]
    err_path = tmp + ".err"
    err_f = open(err_path, "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL,
                           stderr=err_f)
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t = idx / fps
            for (t0, t1, x1, y1, x2, y2, hint) in acts:
                if t < t0 or t > t1:
                    continue
                _repair_frame_region(frame, x1, y1, x2, y2, mask_hint=hint)
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
        code = proc.wait()
        err_f.close()
    if code != 0:
        detail = _tail(err_path)
        _safe_unlink(tmp)
        _safe_unlink(err_path)
        raise RuntimeError(f"ffmpeg 视频编码失败(exit={code}): {detail}")
    _safe_unlink(err_path)
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


def _tail(path: str, limit: int = 400) -> str:
    """取错误日志尾部(供线上定位 ffmpeg 失败原因)。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace").strip()
    return text[-limit:]


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
