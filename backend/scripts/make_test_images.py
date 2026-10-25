"""生成图片去水印测试数据并验证图片管线。

测试数据来源（两类，共 5 张）：
  A. 真实水印帧 —— 从三个原始视频（抖音/TikTok/小红书）抽取带真实水印的帧
  B. 合成水印图 —— 从"去水印成品视频"抽干净帧，用 OpenCV 合成
     抖音 / TikTok / 小红书风格白字水印（带阴影，位置贴近真实布局，
     ground truth 已知，可精确评估检测召回与修复质量）

随后对每张图调用后端图片管线（检测 → inpaint），并把
  - 带水印原图 / 检测标注图 / 去水印成品
统一拷贝到项目根 results/ 目录供交付验证。

用法: python scripts/make_test_images.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import OUTPUTS, TEMP, TEST_DIR, UPLOADS  # noqa: E402
from app.services import pipeline, remover  # noqa: E402

IMG_DIR = TEST_DIR / "images"
RESULTS = BACKEND.parent / "results"
FONT = cv2.FONT_HERSHEY_SIMPLEX
AA = cv2.LINE_AA

XHS_ORIG = UPLOADS / "e6fed0a00cf8.mp4"      # 小红书原始视频(带水印)
DOUYIN_ORIG = TEST_DIR / "抖音.mp4"
TIKTOK_ORIG = TEST_DIR / "Tiktok.mp4"


def build_scene(W: int = 1280, H: int = 720) -> np.ndarray:
    """程序生成暗调黄昏山谷场景(渐变天空+星点+山脉剪影+噪声纹理)。
    作为合成水印测试的背景：无继承伪影、水印 ground truth 完全已知。"""
    rng = np.random.default_rng(42)
    top = np.array([96, 74, 48], np.float64)   # BGR 上部暗蓝
    bot = np.array([40, 34, 26], np.float64)   # 下部暖暗
    rows = np.linspace(0, 1, H)[:, None]
    grad = top[None, :] * (1 - rows) + bot[None, :] * rows
    img = np.clip(np.repeat(grad[:, None, :], W, axis=1), 0,
                  255).astype(np.uint8)

    def draw_ridge(y_base, amp, color):
        xs = np.arange(0, W + 8, 8)
        ys = y_base + np.cumsum(rng.normal(0, amp, len(xs)))
        ys = np.clip(ys, 0, H - 1).astype(int)
        pts = np.vstack([np.column_stack([xs, ys]),
                         [[W, H], [0, H]]]).astype(np.int32)
        cv2.fillPoly(img, [pts], color)

    draw_ridge(int(H * 0.72), 14, (52, 44, 38))   # 远山
    draw_ridge(int(H * 0.84), 10, (30, 26, 24))   # 近山
    cv2.rectangle(img, (0, int(H * 0.95)), (W, H), (24, 22, 20), -1)

    for _ in range(160):                          # 星点
        x = int(rng.integers(0, W))
        y = int(rng.integers(0, int(H * 0.6)))
        b = int(rng.integers(140, 230))
        cv2.circle(img, (x, y), int(rng.integers(0, 2)), (b, b, b), -1)

    img = np.clip(img.astype(np.float64)
                  + rng.normal(0, 13.0, img.shape), 0, 255).astype(np.uint8)
    return img


def extract(src: Path, t: float, out: Path) -> Path:
    tmp = TEMP / "_frame_tmp.jpg"
    assert remover.extract_frame(str(src), t, str(tmp)), f"抽帧失败 {src}@{t}"
    img = cv2.imread(str(tmp))
    assert img is not None, f"读取帧失败 {tmp}"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    tmp.unlink()
    return out


def put_white_text(img, text, org, scale=1.0, thick=2, shadow=True):
    """白色前景 + 深色阴影/描边，模拟真实平台水印样式。"""
    x, y = org
    if shadow:
        cv2.putText(img, text, (x + 2, y + 2), FONT, scale, (25, 25, 25),
                     thick + 2, AA)
    cv2.putText(img, text, (x, y), FONT, scale, (255, 255, 255), thick, AA)


def add_douyin_style(img):
    """抖音风格: 左上 logo+账号, 右下 '抖音号'(贴边, 避开字幕保护带)。"""
    h, w = img.shape[:2]
    put_white_text(img, "DOUYIN", (28, int(h * 0.075)), 0.9, 2)
    put_white_text(img, "@clearflow_test", (28, int(h * 0.115)), 0.62, 2)
    put_white_text(img, "DOUYIN No.88888", (w - 280, h - 26), 0.55, 2)
    return img


def add_tiktok_style(img):
    """TikTok 风格: 左侧中部 logo+用户名(竖屏常见位置), 右下 logo。"""
    h, w = img.shape[:2]
    put_white_text(img, "TikTok", (26, int(h * 0.30)), 0.95, 2)
    put_white_text(img, "@whoami_123", (26, int(h * 0.345)), 0.55, 2)
    put_white_text(img, "TikTok", (int(w * 0.76), h - 26), 0.7, 2)
    return img


def add_xhs_style(img):
    """小红书风格: 右上头像圆+用户名(贴右边缘), 左下平台字样。"""
    h, w = img.shape[:2]
    cx, cy, r = w - 52, int(h * 0.085), 28
    cv2.circle(img, (cx, cy), r + 2, (25, 25, 25), -1, AA)
    cv2.circle(img, (cx, cy), r, (240, 240, 240), -1, AA)
    put_white_text(img, "lazy_cat", (w - 176, int(h * 0.085) + 8), 0.6, 2)
    put_white_text(img, "XIAOHONGSHU", (24, h - 34), 0.7, 2)
    return img


def process_image(path: Path) -> pipeline.Task:
    task = pipeline.create_task("image", str(path), path.suffix, source="test")
    task.input_path = str(path)
    pipeline._process_image(task)  # noqa: SLF001
    return task


def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    # ---------- A. 真实水印帧 ----------
    real_frames = [
        extract(DOUYIN_ORIG, 2.0, IMG_DIR / "real_douyin_frame.jpg"),
        extract(TIKTOK_ORIG, 10.0, IMG_DIR / "real_tiktok_frame.jpg"),
        extract(XHS_ORIG, 60.0, IMG_DIR / "real_xhs_frame.jpg"),
    ]

    # ---------- B. 合成水印图(程序生成场景 + 已知水印) ----------
    scene = build_scene()
    synth_specs = [
        ("synth_douyin.jpg", add_douyin_style),
        ("synth_tiktok.jpg", add_tiktok_style),
        ("synth_xhs.jpg", add_xhs_style),
    ]
    synth_imgs = []
    for name, adder in synth_specs:
        img = adder(scene.copy())
        out = IMG_DIR / name
        cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        synth_imgs.append(out)

    # ---------- 跑图片管线 ----------
    print("\n===== 图片去水印管线验证 =====")
    all_imgs = real_frames + synth_imgs
    summary = []
    for p in all_imgs:
        task = process_image(p)
        n = len(task.regions)
        status = "OK " if task.status == "done" else "FAIL"
        print(f"[{status}] {p.name:<24} 检出水印区域: {n}")
        if task.status == "done":
            detect = OUTPUTS / task.detect_preview
            clean = OUTPUTS / task.output_name
            stem = p.stem
            shutil.copy(detect, RESULTS / f"{stem}_detect.jpg")
            shutil.copy(clean, RESULTS / f"{stem}_clean.jpg")
            shutil.copy(p, RESULTS / p.name)
        else:
            print(f"      错误: {task.error}")
        summary.append((p.name, n, task.status))

    ok = sum(1 for _, n, s in summary if s == "done" and n > 0)
    print(f"\n共 {len(summary)} 张, 检出≥1处且处理成功: {ok} 张")
    print(f"结果已拷贝到: {RESULTS}")


if __name__ == "__main__":
    main()
