"""端到端测试：处理 test 视频生成无水印成品。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import pipeline

TEST = Path("/Users/grass/Desktop/AI/video/test")

for name in ("Tiktok.mp4", "抖音.mp4"):
    src = TEST / name
    print(f"\n===== 处理 {name} =====")
    task = pipeline.create_task("video", str(src), ".mp4", source="test")
    t0 = time.time()
    pipeline._run(task)
    dt = time.time() - t0
    print(f"status={task.status} 用时={dt:.1f}s")
    if task.error:
        print(f"ERROR: {task.error}")
        continue
    print(f"tracks: {task.tracks}")
    print(f"meta: {task.meta}")
    out = Path(task.output_name)
    print(f"output: /Users/grass/Desktop/AI/video/backend/storage/outputs/{out}")
print("\ndone")
