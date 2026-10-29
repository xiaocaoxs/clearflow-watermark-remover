"""水印检测算法模块。

策略（三通道、纯规则、零模型依赖）：
  阶段1 —— 平台先验候选区域：各平台水印(TikTok/抖音/小红书)出现位置已知(角落/底部条带)
  阶段2 —— 区域内亮/暗双通道形态学分析：
            * 亮通道: 白色文字/logo 前景 (阈值二值化)
            * 暗通道: 水印阴影/深色图形 (反阈值)
            * 闭运算+膨胀把文字笔画连成块 → 轮廓外接矩形
            * 形状/面积/填充率过滤误检
  视频模式：多时间点采样 → 位置聚类成时间轨(Track)，天然支持 TikTok 移动水印。
  阶段3(仅视频) —— 静态叠加层时序累积：白字压在明亮背景(白墙/枕头)上时，
            单帧全局亮度阈值会把文字和背景连成一块而被尺寸过滤丢掉；
            改用局部对比度(顶帽)提取"比周边亮的结构"，再跨帧累积 ——
            水印是固定叠加层，同一像素在绝大多数帧里都满足该特征，
            画面内容则会漂移。累积占比达阈值即判为静态水印。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import cv2
import numpy as np

# 候选区域 (名称, x, y, w, h) —— 相对坐标，覆盖已知平台水印位置
# 实测布局: 抖音=左上(前段)+右下(全程) 抖音号/logo/搜索标签;
#           TikTok竖屏=左侧中部(随时间移至右侧); 小红书=右上/右下/底部
CANDIDATE_ZONES = [
    ("top-left",     0.00, 0.00, 0.50, 0.18),
    ("top-right",    0.50, 0.00, 0.50, 0.18),
    ("left-mid",     0.00, 0.12, 0.30, 0.42),
    ("right-mid",    0.70, 0.12, 0.30, 0.42),
    ("bottom-left",  0.00, 0.78, 0.42, 0.22),
    ("bottom-right", 0.55, 0.70, 0.45, 0.30),
]

BRIGHT_THRESHOLD = 193  # 白色前景亮度阈值
DARK_THRESHOLD = 58     # 深色阴影阈值
BRIGHT_LAP_MIN = 400    # 亮通道候选的拉普拉斯下限: 过滤云彩/亮墙等平坦亮部误检
MIN_W = 24              # 最小矩形宽
MIN_H = 7               # 最小矩形高
MAX_ZONE_COVER = 0.55    # 矩形不许超过候选区域面积的一半(防背景误检)
MIN_FILL = 0.12         # 原二值图在矩形内的填充率下限
MAX_REGION_W = 0.34     # 单区域最大宽度(相对帧宽) —— 超过视为内容块
MAX_REGION_H = 0.22     # 单区域最大高度(相对帧高, 兼容 logo+两行文字+阴影)
SUBTITLE_GUARD_X = (0.30, 0.70)  # 底部中央字幕保护带(相对宽度)
SUBTITLE_BAND_Y = 0.82   # 底部字幕带: 起始高度(相对帧高)
SUBTITLE_MIN_W = 0.20    # 底部字幕带内, 宽度超过此比例(相对帧宽)视为字幕横排
EDGE_MARGIN = 0.07      # 贴边判定: 角标常离边 30px 左右，不能要求贴死像素
PAD = 6                 # 输出矩形外扩像素

# 静态叠加层通道(视频专用) —— 局部对比度 + 跨帧累积
OVERLAY_TOPHAT_K = 19     # 顶帽核边长(基准帧宽 944px, 按实际宽度缩放)
OVERLAY_TOPHAT_TH = 26    # 顶帽响应阈值: 比周边亮多少才算水印笔画
OVERLAY_MIN_FRAC = 0.62   # 判定"静态叠加"的最小时序占比
OVERLAY_BOX_PRESENCE = 0.15  # 单帧内该框的笔画占比达到此值即视为"在场"
OVERLAY_FILL_MIN = 0.02      # 轮廓内笔画占比下限

BOTTOM_BAND_Y = 0.80     # 底部条带起点(相对帧高)
BOTTOM_MIN_HITS = 8      # 底部条带内的轨迹至少需要的命中次数
VIDEO_MIN_HITS = 5       # 视频轨迹的最少命中数: 低于此值多为画面内容瞬时误检


@dataclass
class Region:
    """帧坐标系下的水印矩形区域。"""
    x: int
    y: int
    w: int
    h: int
    conf: float = 0.85

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- 基础几何工具 ----------------

def _iou(a, b) -> float:
    """a,b: (x1,y1,x2,y2)"""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / float(area_a + area_b - inter)


def _near(a, b, dist=14) -> bool:
    """边界间距小于 dist 视为紧邻(需合并)。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if ax1 > bx2 + dist or bx1 > ax2 + dist:
        return False
    if ay1 > by2 + dist or by1 > ay2 + dist:
        return False
    return True


def _merge_rects_capped(rects, W, H, iou_th=0.02):
    """合并笔画，但拒绝并成超过水印尺寸上限的框。"""
    boxes = [list(r) for r in rects]
    changed = True
    while changed and len(boxes) > 1:
        changed = False
        out = []
        while boxes:
            b = boxes.pop()
            i = 0
            while i < len(boxes):
                a = boxes[i]
                union = [min(b[0], a[0]), min(b[1], a[1]),
                         max(b[2], a[2]), max(b[3], a[3])]
                too_big = ((union[2] - union[0]) > MAX_REGION_W * W or
                           (union[3] - union[1]) > MAX_REGION_H * H)
                if not too_big and (_iou(b, a) > iou_th or _near(b, a)):
                    b = union
                    boxes.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def _merge_rects(rects, iou_th=0.02):
    """迭代合并重叠/紧邻矩形，取外接并集。rects: [(x1,y1,x2,y2)]"""
    boxes = [list(r) for r in rects]
    changed = True
    while changed and len(boxes) > 1:
        changed = False
        out = []
        while boxes:
            b = boxes.pop()
            i = 0
            while i < len(boxes):
                a = boxes[i]
                if _iou(b, a) > iou_th or _near(b, a):
                    b = [min(b[0], a[0]), min(b[1], a[1]),
                         max(b[2], a[2]), max(b[3], a[3])]
                    boxes.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


# ---------------- 区域内分析 ----------------

def _rect_fill(binary: np.ndarray, x, y, w, h) -> float:
    sub = binary[y:y + h, x:x + w]
    if sub.size == 0:
        return 0.0
    return float((sub > 0).mean())


def _analyze_zone(gray: np.ndarray, zx: int, zy: int, zw: int, zh: int):
    """在单个候选区域内检测水印元素，返回帧坐标矩形列表 (x1,y1,x2,y2)。"""
    if zw < 40 or zh < 20:
        return []
    roi = gray[zy:zy + zh, zx:zx + zw]
    rects = []

    bright = cv2.threshold(roi, BRIGHT_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
    dark = cv2.threshold(roi, DARK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)[1]

    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    dil_k = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 5))

    for is_bright, binary in ((True, bright), (False, dark)):
        processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_k)
        dil = cv2.dilate(processed, dil_k)
        contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w < MIN_W or h < MIN_H:
                continue
            if (w + 4) * (h + 4) > MAX_ZONE_COVER * zw * zh:
                continue  # 几乎覆盖整个候选区 → 背景整体偏亮/偏暗
            # 均匀块过滤: letterbox 黑边/纯色背景不是水印
            roi_orig = roi[y:y + h, x:x + w]
            if roi_orig.size and float(roi_orig.std()) < 10:
                continue
            # 亮通道: 平坦的明亮画面内容(云彩/白墙/过曝)非文字水印, 用锐度过滤
            if is_bright and cv2.Laplacian(roi_orig, cv2.CV_64F).var() < BRIGHT_LAP_MIN:
                continue
            fill = _rect_fill(binary, x, y, w, h)
            if fill < MIN_FILL:
                continue
            if h > 1.3 * w and w < 0.18 * zw:
                continue  # 细高竖条 → 更可能是画面内容
            rects.append((x, y, x + w, y + h))

    return [(x + zx, y + zy, x2 + zx, y2 + zy) for (x, y, x2, y2) in rects]


# ---------------- 白字通道（仅图片模式） ----------------
# 半透明白色水印（如小红书用户名）经视频压缩后绝对亮度可低至 ~130，
# 固定亮阈值会整体漏检。其本质特征是「低饱和 + 局部显著」：
#   * HSV 亮度 > WHITE_V_MIN 且饱和度 < WHITE_S_MAX → 近乎消色差的白字前景
#   * 白字候选区与已检出区域重叠 → 视为同一水印的就地扩展
#   * 独立白字候选区需同时通过 锐度/面积/边缘密度 三重门，防止把
#     月光、衣袍高光等低饱和画面内容误判为水印
WHITE_V_MIN = 100
WHITE_S_MAX = 70
WHITE_BBOX_LAP_MIN = 400   # 单块候选的拉普拉斯下限: 过滤柱子/墙面/天空等平坦低饱和画面内容
WHITE_LAP_MIN = 1500       # 独立候选区拉普拉斯方差下限: 文字笔画是锐利高频结构
WHITE_AREA_MIN = 6000      # 独立候选区最小面积
WHITE_CANNY_MAX = 0.15     # Canny 边缘密度上限: 光晕类误检边缘稀疏或过密


def _white_zone_rects(roi_bgr: np.ndarray, zx: int, zy: int,
                      zw: int, zh: int) -> list:
    """低饱和白字通道：捕获半透明白色水印文字/图形。"""
    if zw < 40 or zh < 20:
        return []
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    binary = np.where((hsv[..., 2] > WHITE_V_MIN) &
                      (hsv[..., 1] < WHITE_S_MAX),
                      255, 0).astype(np.uint8)
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    dil_k = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 5))
    processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_k)
    dil = cv2.dilate(processed, dil_k)
    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    rects = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < MIN_W or h < MIN_H:
            continue
        if (w + 4) * (h + 4) > MAX_ZONE_COVER * zw * zh:
            continue
        sub = gray[y:y + h, x:x + w]
        if sub.size and float(sub.std()) < 10:
            continue
        # 平坦的低饱和画面内容(墙/柱/天空)非文字: 用锐度预过滤
        if cv2.Laplacian(sub, cv2.CV_64F).var() < WHITE_BBOX_LAP_MIN:
            continue
        if _rect_fill(binary, x, y, w, h) < MIN_FILL:
            continue
        if h > 1.3 * w and w < 0.18 * zw:
            continue
        rects.append((x + zx, y + zy, x + zx + w, y + zy + h))
    return rects


def _white_sharp_ok(gray: np.ndarray, x1: int, y1: int,
                    x2: int, y2: int) -> bool:
    """独立白字候选区的三重准入校验（锐度 + 面积 + 边缘密度）。"""
    w, h = x2 - x1, y2 - y1
    if w * h < WHITE_AREA_MIN:
        return False
    sub = gray[y1:y2, x1:x2]
    if sub.size == 0:
        return False
    lap = cv2.Laplacian(sub, cv2.CV_64F).var()
    if lap < WHITE_LAP_MIN:
        return False
    edges = cv2.Canny(sub, 60, 160)
    return float((edges > 0).mean()) < WHITE_CANNY_MAX


def _is_edge_attached(x1, y1, x2, y2, W, H) -> bool:
    """贴边判定: 平台水印必然贴近画面边缘(角标/条带), 中央块多为内容。"""
    mx = max(8.0, EDGE_MARGIN * W)
    my = max(8.0, EDGE_MARGIN * H)
    return (x1 <= mx or y1 <= my or
            x2 >= W - mx or y2 >= H - my)


def _passes_global(x1: int, y1: int, x2: int, y2: int,
                   W: int, H: int) -> tuple | None:
    """全局过滤(尺寸/贴边/字幕保护)，通过则返回外扩 PAD 后的矩形。"""
    x = max(0, x1 - PAD)
    y = max(0, y1 - PAD)
    x2 = min(W, x2 + PAD)
    y2 = min(H, y2 + PAD)
    w, h = x2 - x, y2 - y
    if w < MIN_W or h < MIN_H:
        return None
    # 尺寸限制: 超大块是画面内容而非水印
    if w > MAX_REGION_W * W or h > MAX_REGION_H * H:
        return None
    # 贴边必须: 平台水印都在画面边缘
    if not _is_edge_attached(x, y, x2, y2, W, H):
        return None
    # 字幕保护: 底部中央区域的横向长条(字幕)
    cx = (x + x2) / 2.0 / W
    if y > 0.80 * H and SUBTITLE_GUARD_X[0] < cx < SUBTITLE_GUARD_X[1]:
        return None
    # 字幕保护: 底部字幕带内的宽横排块 —— 字幕居中偏左时中心点会落在
    # 中央带之外, 只看中心点会漏判, 这里按"底部 + 够宽"再兜一次。
    if y > SUBTITLE_BAND_Y * H and w > SUBTITLE_MIN_W * W:
        return None
    return (x, y, x2, y2)


def _overlap_area(a, b) -> int:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _augment_white_text(frame_bgr: np.ndarray, gray: np.ndarray,
                        regions: list[Region]) -> list[Region]:
    """图片模式白字通道增强：
    1) 与已检出区域重叠的白字候选 → 就地扩展该区域(覆盖半透明用户名等)
    2) 独立候选区需通过锐度/面积/边缘密度三重门才追加为新区域
    """
    H, W = frame_bgr.shape[:2]
    white_rects = []
    for _name, rx, ry, rw, rh in CANDIDATE_ZONES:
        zx, zy = int(rx * W), int(ry * H)
        zw, zh = int(rw * W), int(rh * H)
        white_rects.extend(_white_zone_rects(
            frame_bgr[zy:zy + zh, zx:zx + zw], zx, zy, zw, zh))
    if not white_rects:
        return regions

    cand = []
    for r in _merge_rects(white_rects):
        pr = _passes_global(r[0], r[1], r[2], r[3], W, H)
        if pr:
            cand.append(pr)
    if not cand:
        return regions

    boxes = [[r.x, r.y, r.x + r.w, r.y + r.h] for r in regions]
    for (cx1, cy1, cx2, cy2) in cand:
        c_area = (cx2 - cx1) * (cy2 - cy1)
        expanded = False
        for b in boxes:
            if _overlap_area((cx1, cy1, cx2, cy2), b) < 0.08 * c_area:
                continue
            nx1, ny1 = min(b[0], cx1), min(b[1], cy1)
            nx2, ny2 = max(b[2], cx2), max(b[3], cy2)
            if ((nx2 - nx1) <= MAX_REGION_W * W and
                    (ny2 - ny1) <= MAX_REGION_H * H):
                b[0], b[1], b[2], b[3] = nx1, ny1, nx2, ny2
                expanded = True
                break
        if expanded:
            continue
        # 独立候选区: 三重门校验
        if _white_sharp_ok(gray, cx1, cy1, cx2, cy2):
            boxes.append([cx1, cy1, cx2, cy2])

    return [Region(x=b[0], y=b[1], w=b[2] - b[0], h=b[3] - b[1])
            for b in boxes]


def detect_regions(frame_bgr: np.ndarray,
                   white_text: bool = False) -> list[Region]:
    """对单帧(或图片)检测水印区域。

    white_text=True 时启用白字通道增强（图片模式专用；视频模式依赖
    时序验证过滤误检，保持双通道不变以免回归）。
    """
    H, W = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    all_rects = []
    for _name, rx, ry, rw, rh in CANDIDATE_ZONES:
        zx, zy = int(rx * W), int(ry * H)
        zw, zh = int(rw * W), int(rh * H)
        all_rects.extend(_analyze_zone(gray, zx, zy, zw, zh))

    merged = _merge_rects(all_rects)

    # 并集会把角标和旁边的亮部合成超大框，随后被尺寸过滤整块丢掉。
    # 超大框丢弃后，把仍符合尺寸的原始小框拣回来。
    kept_boxes = []
    for (x1, y1, x2, y2) in merged:
        pr = _passes_global(x1, y1, x2, y2, W, H)
        if pr:
            kept_boxes.append(pr)
            continue
        for (a, b, c, d) in all_rects:
            if a < x1 - 2 or b < y1 - 2 or c > x2 + 2 or d > y2 + 2:
                continue
            member = _passes_global(a, b, c, d, W, H)
            if member:
                kept_boxes.append(member)
    kept_boxes = _merge_rects_capped(kept_boxes, W, H)

    regions = []
    for (x1, y1, x2, y2) in kept_boxes:
        regions.append(Region(x=x1, y=y1, w=x2 - x1, h=y2 - y1))

    if white_text:
        regions = _augment_white_text(frame_bgr, gray, regions)
    return regions


# ---------------- 视频时序轨迹 ----------------

@dataclass
class Track:
    """水印的时空轨迹：一个矩形在 [t0,t1] 时间段内出现。"""
    x1: int
    y1: int
    x2: int
    y2: int
    t0: float
    t1: float
    hits: int = 1
    frame_idx: list = None  # 命中的采样帧索引(时序验证用)
    obs_x1: list = None
    obs_y1: list = None
    obs_x2: list = None
    obs_y2: list = None
    mask: np.ndarray = None  # 跨帧累积的笔画掩码(相对轨迹框, 修复时复用)

    def __post_init__(self):
        if self.frame_idx is None:
            self.frame_idx = []
        if self.obs_x1 is None:
            self.obs_x1 = [self.x1]
            self.obs_y1 = [self.y1]
            self.obs_x2 = [self.x2]
            self.obs_y2 = [self.y2]

    @property
    def w(self):
        return self.x2 - self.x1

    @property
    def h(self):
        return self.y2 - self.y1


def _track_iou(tr: Track, r: Region) -> float:
    return _iou((tr.x1, tr.y1, tr.x2, tr.y2), (r.x, r.y, r.x2, r.y2))


def _size_compatible(tr: Track, r: Region, ratio: float = 1.6) -> bool:
    tw, th = max(1, tr.w), max(1, tr.h)
    rw, rh = max(1, r.w), max(1, r.h)
    return ((1 / ratio) <= (rw / tw) <= ratio and
            (1 / ratio) <= (rh / th) <= ratio)


def _refit_track(tr: Track) -> None:
    """用各次检测的中位数作为修复框，避免一次误检把轨迹撑满画面。"""
    tr.x1 = int(np.median(tr.obs_x1))
    tr.y1 = int(np.median(tr.obs_y1))
    tr.x2 = int(np.median(tr.obs_x2))
    tr.y2 = int(np.median(tr.obs_y2))


def build_tracks(samples, gap=1.2, min_hits=3, frames_gray=None):
    """samples: [(t, [Region...])] 按 t 升序。
    frames_gray: 与 samples 对齐的灰度帧列表(可选) —— 用于时序稳定性验证。
    返回 Track 列表 —— 支持 TikTok 水印移动(不同位置→不同 Track)。
    """
    active: list[Track] = []
    finished: list[Track] = []

    for fi, (t, regions) in enumerate(samples):
        for r in regions:
            best_iou, best_idx = 0.0, -1
            for i, tr in enumerate(active):
                if t - tr.t1 > gap or fi in tr.frame_idx:
                    continue
                iou = _track_iou(tr, r)
                # 尺寸差很大的框不是同一个角标，并进去会把水印框撑到无法整段抹掉
                if iou > 0.12 and iou > best_iou and _size_compatible(tr, r):
                    best_iou, best_idx = iou, i
            if best_idx >= 0:
                tr = active[best_idx]
                tr.obs_x1.append(r.x)
                tr.obs_y1.append(r.y)
                tr.obs_x2.append(r.x2)
                tr.obs_y2.append(r.y2)
                _refit_track(tr)
                tr.t1 = t
                tr.hits += 1
                tr.frame_idx.append(fi)
            else:
                tr_new = Track(r.x, r.y, r.x2, r.y2, t, t)
                tr_new.frame_idx.append(fi)
                active.append(tr_new)

        rest = []
        for tr in active:
            if t - tr.t1 > gap:
                finished.append(tr)
            else:
                rest.append(tr)
        active = rest

    finished.extend(active)
    keep = [tr for tr in finished if tr.hits >= min_hits]
    keep = _temporal_verify(keep, samples, frames_gray)
    keep = _merge_tracks_spatially(keep)
    return keep


def _merge_tracks_spatially(tracks):
    """仅合并时间相交且位置重叠的轨迹，保留水印离场的时间间隔。"""
    if len(tracks) <= 1:
        return tracks
    result = list(tracks)
    changed = True
    while changed:
        changed = False
        out = []
        while result:
            tr = result.pop()
            i = 0
            while i < len(result):
                a = result[i]
                if (max(tr.t0, a.t0) <= min(tr.t1, a.t1) and
                        _iou((tr.x1, tr.y1, tr.x2, tr.y2),
                             (a.x1, a.y1, a.x2, a.y2)) > 0.30):
                    frame_idx = sorted(set(tr.frame_idx + a.frame_idx))
                    hits = len(frame_idx) if frame_idx else max(tr.hits, a.hits)
                    tr = Track(min(tr.x1, a.x1), min(tr.y1, a.y1),
                               max(tr.x2, a.x2), max(tr.y2, a.y2),
                               min(tr.t0, a.t0), max(tr.t1, a.t1), hits)
                    tr.frame_idx = frame_idx
                    result.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(tr)
        result = out
    return result


def _temporal_verify(tracks, samples, frames_gray,
                     min_static=0.10, std_th=20.0):
    """时序稳定性验证(静态叠加层原理)：

    水印是叠加在画面上的静态图层 → 区域内水印像素随时间标准差≈0；
    画面内容(人物/光影)持续运动 → 时间标准差高。
    只用 Track 的命中帧验证: 命中帧水印必然在场, 误检块在命中帧间
    也随画面运动, 静态比例低 → 丢弃。
    """
    if not frames_gray or len(frames_gray) < 4 or not tracks:
        return tracks
    kept = []
    for tr in tracks:
        idx = tr.frame_idx or []
        if len(idx) < 3:
            kept.append(tr)
            continue
        stack = np.stack([frames_gray[i] for i in idx]).astype(np.float32)
        H, W = stack.shape[1], stack.shape[2]
        y1, y2 = max(0, tr.y1), min(H, tr.y2)
        x1, x2 = max(0, tr.x1), min(W, tr.x2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        roi = stack[:, y1:y2, x1:x2]
        std_map = roi.std(axis=0)
        static_ratio = float((std_map < std_th).mean())
        if static_ratio >= min_static:
            kept.append(tr)
    return kept


# ---------------- 静态叠加层通道(视频专用) ----------------

def local_contrast_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """候选区内的"局部更亮结构"掩码(白顶帽)。

    全局亮度阈值无法区分"白字"和"本来就白的背景"(白墙/枕头/过曝)；
    顶帽只保留比自身邻域亮出 OVERLAY_TOPHAT_TH 以上的细节，
    平滑背景与缓慢渐变的亮部被压掉，白字笔画得以保留。
    """
    H, W = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    k = max(9, int(round(OVERLAY_TOPHAT_K * W / 944.0)) | 1)
    se = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    mask = np.zeros((H, W), np.uint8)
    for _name, rx, ry, rw, rh in CANDIDATE_ZONES:
        zx, zy = int(rx * W), int(ry * H)
        zw, zh = int(rw * W), int(rh * H)
        roi = gray[zy:zy + zh, zx:zx + zw]
        if roi.size == 0:
            continue
        tophat = cv2.morphologyEx(roi, cv2.MORPH_TOPHAT, se)
        mask[zy:zy + zh, zx:zx + zw] = cv2.threshold(
            tophat, OVERLAY_TOPHAT_TH, 255, cv2.THRESH_BINARY)[1]
    return mask


def build_overlay_tracks(masks, times, min_frac: float = OVERLAY_MIN_FRAC):
    """把逐帧局部对比度掩码累积成"静态叠加层"轨迹。

    masks: 与 times 对齐的 local_contrast_mask 结果。
    只有同一像素在 min_frac 以上的帧里都表现为"局部更亮结构"时才保留 ——
    水印是固定叠加层，满足该条件；移动的画面内容不满足。
    """
    n = len(masks)
    if n == 0:
        return []
    H, W = masks[0].shape
    acc = np.zeros((H, W), np.float32)
    for m in masks:
        acc += (m > 0)
    persist = (acc >= min_frac * n).astype(np.uint8) * 255
    if not np.any(persist):
        return []

    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    dil_k = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    dil = cv2.dilate(cv2.morphologyEx(persist, cv2.MORPH_CLOSE, close_k), dil_k)
    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < MIN_W or h < MIN_H:
            continue
        if float((persist[y:y + h, x:x + w] > 0).mean()) < OVERLAY_FILL_MIN:
            continue
        pr = _passes_global(x, y, x + w, y + h, W, H)
        if pr:
            boxes.append(pr)
    if not boxes:
        return []
    boxes = _merge_rects_capped(boxes, W, H)

    tracks = []
    for (x1, y1, x2, y2) in boxes:
        sub = [(m[y1:y2, x1:x2] > 0) for m in masks]
        present = [i for i, s in enumerate(sub)
                   if s.size and float(s.mean()) >= OVERLAY_BOX_PRESENCE]
        if len(present) < min_frac * n:
            continue
        tr = Track(x1, y1, x2, y2,
                   float(times[present[0]]), float(times[present[-1]]),
                   hits=len(present))
        tr.frame_idx = present
        # 跨帧稳定的笔画位置即为水印本体; 修复时直接复用,
        # 避免某几帧对比度不足(白字压白底)时抠不出形状而漏修。
        stroke = np.where(acc[y1:y2, x1:x2] >= min_frac * n,
                          255, 0).astype(np.uint8)
        if np.any(stroke):
            tr.mask = cv2.dilate(stroke, np.ones((3, 3), np.uint8))
        tracks.append(tr)
    return tracks


def merge_track_sets(primary, extra):
    """把 extra 中与 primary 位置重叠的轨迹并入, 其余追加。

    逐帧检测拿不到的框(低对比度)由静态叠加层补上；两者指向同一水印时
    取外接并集与时间并集，避免同一区域被重复修复。
    """
    result = [Track(tr.x1, tr.y1, tr.x2, tr.y2, tr.t0, tr.t1, tr.hits,
                    list(tr.frame_idx), mask=tr.mask) for tr in primary]
    for ex in extra:
        hit = False
        for tr in result:
            if _iou((tr.x1, tr.y1, tr.x2, tr.y2),
                    (ex.x1, ex.y1, ex.x2, ex.y2)) < 0.05:
                continue
            nx1, ny1 = min(tr.x1, ex.x1), min(tr.y1, ex.y1)
            nx2, ny2 = max(tr.x2, ex.x2), max(tr.y2, ex.y2)
            # 框被撑大后原有笔画掩码不再对齐, 只在框不变时沿用
            keep_mask = ex.mask if (nx1, ny1, nx2, ny2) == (ex.x1, ex.y1,
                                                            ex.x2, ex.y2) \
                else (tr.mask if (nx1, ny1, nx2, ny2) == (tr.x1, tr.y1,
                                                          tr.x2, tr.y2) else None)
            tr.x1, tr.y1, tr.x2, tr.y2 = nx1, ny1, nx2, ny2
            tr.t0, tr.t1 = min(tr.t0, ex.t0), max(tr.t1, ex.t1)
            tr.hits = max(tr.hits, ex.hits)
            tr.mask = keep_mask
            tr.frame_idx = sorted(set(tr.frame_idx) | set(ex.frame_idx))
            hit = True
            break
        if not hit:
            result.append(ex)
    return result


def filter_bottom_tracks(tracks, H: int, min_hits: int = BOTTOM_MIN_HITS):
    """底部条带内的轨迹需有足够命中数才保留。

    底部条带是字幕高发区: 字幕随台词出现/消失, 只在某一两句台词期间被检出,
    命中数远低于整段稳定叠加的平台角标。被静态叠加层佐证过的轨迹在合并时
    已取命中数最大值, 因此不会在这里被误杀。
    """
    if H <= 0:
        return tracks
    band = BOTTOM_BAND_Y * H
    return [tr for tr in tracks if tr.y1 <= band or tr.hits >= min_hits]


def draw_regions(frame_bgr: np.ndarray, regions, with_mask=True) -> np.ndarray:
    """在帧上绘制检测标注(红框+半透明填充)，用于前端可视化。"""
    vis = frame_bgr.copy()
    overlay = vis.copy()
    for r in regions:
        cv2.rectangle(overlay, (r.x, r.y), (r.x2, r.y2), (60, 60, 235), -1)
    if with_mask:
        vis = cv2.addWeighted(overlay, 0.32, vis, 0.68, 0)
    for r in regions:
        cv2.rectangle(vis, (r.x, r.y), (r.x2, r.y2), (60, 60, 235), 2)
    return vis
