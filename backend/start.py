"""生产启动入口。

读取 PORT 环境变量（默认 3000）并绑定 0.0.0.0，供容器/托管平台直接 `python start.py` 拉起。
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "3000")),
        log_level="info",
    )
