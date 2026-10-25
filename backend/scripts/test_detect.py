"""检测算法快速验证：对 test 视频采样帧做水印检测并输出标注图。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from app.services import detector

TEST = Path("/Users/grass/Desktop/AI/video/test")
OUT = Path("/Users/grass/Desktop/AI/video/backend/storage/temp")
OUT.mkdir(parents=True, exist_ok=True)

for video_name in ("Tiktok.mp4", "抖音.mp4"):
    cap = cv2.VideoCapture(str(TEST / video_name))
    if not cap.isOpened():
        print(f"[FAIL] 打不开 {video_name}")
        continue
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur = frames / fps
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"\n=== {video_name}: {W}x{H}, {dur:.1f}s ===")

    samples, frames_gray = [], []
    n = min(48, max(12, int(dur / 0.8)))
    step = dur / n
    for i in range(n):
        t = min(dur - 0.05, i * step)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        regions = detector.detect_regions(frame)
        samples.append((t, regions))
        frames_gray.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()

    tracks = detector.build_tracks(samples, frames_gray=frames_gray)
    print(f"  -> {len(tracks)} tracks:")
    for tr in tracks:
        print(f"     rect=({tr.x1},{tr.y1})-({tr.x2},{tr.y2}) "
              f"t={tr.t0:.1f}-{tr.t1:.1f}s hits={tr.hits}")

    # 输出首帧/中帧标注图
    cap = cv2.VideoCapture(str(TEST / video_name))
    for tag, tt in (("first", 0.3), ("mid", dur / 2)):
        cap.set(cv2.CAP_PROP_POS_MSEC, tt * 1000)
        ok, frame = cap.read()
        if ok:
            regions = detector.detect_regions(frame)
            vis = detector.draw_regions(frame, regions)
            out_file = OUT / f"{video_name}_{tag}.jpg"
            cv2.imwrite(str(out_file), vis)
    cap.release()
print("\ndone")
