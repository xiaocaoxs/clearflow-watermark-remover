"""生成可发布的单端口部署包。

产物目录 deploy/ 结构:
    app/            后端源码(FastAPI)
    static/         前端构建产物(frontend/dist)
    requirements.txt

运行: python scripts/build_deploy.py
前提: 已在 frontend/ 执行 npm run build
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "deploy"


def main() -> int:
    if not (DIST / "index.html").is_file():
        print(f"[!] 缺少前端构建产物: {DIST}\n    先执行 cd frontend && npm run build")
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copytree(
        BACKEND / "app",
        OUT / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(DIST, OUT / "static")
    shutil.copy2(BACKEND / "requirements.txt", OUT / "requirements.txt")
    shutil.copy2(BACKEND / "start.py", OUT / "start.py")

    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"[+] 部署包已生成: {OUT}  ({files} 个文件, {size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
