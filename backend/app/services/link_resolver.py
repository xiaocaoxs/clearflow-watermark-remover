"""分享链接解析模块（插件式策略）。

支持平台:
  - 小红书: xhslink.cn / xiaohongshu.com
  - 抖音:   v.douyin.com / douyin.com / iesdouyin.com
  - TikTok: tiktok.com / vm.tiktok.com

流程: 短链跟随重定向 → 请求页面(移动端UA) → 从页面嵌入 JSON 提取
无水印媒体直链 → 后端代理下载。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
             "Mobile/15E148 Safari/604.1")
DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 "
              "Safari/537.36")

HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ResolverError(Exception):
    pass


def detect_platform(url: str) -> str:
    u = url.lower()
    if "xhslink.cn" in u or "xiaohongshu.com" in u:
        return "xiaohongshu"
    if "douyin" in u:
        return "douyin"
    if "tiktok" in u:
        return "tiktok"
    return "unknown"


def _to_json(safe: str):
    safe = re.sub(r",\s*([}\]])", r"\1", safe)
    return json.loads(safe)


async def parse_link(url: str) -> dict:
    """解析分享链接 → {platform, media_type, url, title}"""
    platform = detect_platform(url)
    if platform == "unknown":
        # 尝试跟随重定向后二次识别
        async with httpx.AsyncClient(follow_redirects=True,
                                     headers=HEADERS, timeout=TIMEOUT) as c:
            r = await c.get(url)
            platform = detect_platform(str(r.url))
            if platform == "unknown":
                raise ResolverError("暂不支持该链接，请直接上传文件")
            url = str(r.url)

    if platform == "xiaohongshu":
        return await _resolve_xhs(url)
    if platform == "douyin":
        return await _resolve_douyin(url)
    if platform == "tiktok":
        return await _resolve_tiktok(url)
    raise ResolverError("暂不支持该链接，请直接上传文件")


# ---------------- 小红书 ----------------

async def _resolve_xhs(url: str) -> dict:
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS,
                                 timeout=TIMEOUT) as c:
        r = await c.get(url)
        r.raise_for_status()
        html = r.text
        final_url = str(r.url)

    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = (title_m.group(1).strip() if title_m else "小红书作品")

    # 1) 页面 __INITIAL_STATE__(新版页面 note 数据常不在其中, 尝试之)
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>",
                  html, re.S)
    if m:
        try:
            data = _to_json(m.group(1))
            note = None
            note_map = (data.get("note", {}).get("noteDetailMap") or {})
            nid = final_url.rstrip("/").split("/")[-1].split("?")[0]
            if nid in note_map:
                note = note_map[nid].get("note", {})
            if note is None and note_map:
                note = next(iter(note_map.values())).get("note", {})
            if note:
                title = note.get("title") or title
                video = note.get("video") or {}
                stream = (video.get("mediaStream") or {})
                for key in ("h264", "h265", "av1"):
                    arr = stream.get(key) or []
                    if arr and arr[0].get("masterUrl"):
                        return {"platform": "xiaohongshu",
                                "media_type": "video",
                                "url": arr[0]["masterUrl"], "title": title}
                images = note.get("imageList") or []
                urls = [img.get("urlDefault") or img.get("url")
                        for img in images]
                urls = [u for u in urls if u]
                if urls:
                    return {"platform": "xiaohongshu", "media_type": "image",
                            "url": urls[0], "title": title,
                            "extra_urls": urls[1:5]}
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    # 2) 页面内嵌 mediaStream masterUrl(含 \u002F 转义)
    urls = re.findall(r'"masterUrl"\s*:\s*"([^"]+)"', html)
    if urls:
        u = urls[0].replace("\\u002F", "/").replace("\\/", "/")
        if u.startswith("http://"):
            u = "https://" + u[len("http://"):]
        return {"platform": "xiaohongshu", "media_type": "video",
                "url": u, "title": title}

    # 3) og meta
    m = re.search(r'property="og:video"\s+content="([^"]+)"', html)
    if m:
        return {"platform": "xiaohongshu", "media_type": "video",
                "url": m.group(1).replace("&amp;", "&"), "title": title}
    m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if m:
        return {"platform": "xiaohongshu", "media_type": "image",
                "url": m.group(1).replace("&amp;", "&"), "title": title}

    # 4) 兜底: 正则找 sns 直链
    m = re.search(r'https://sns-video[^"\\\s]+?\.(?:mp4|mov)', html)
    if m:
        return {"platform": "xiaohongshu", "media_type": "video",
                "url": m.group(0), "title": title}

    raise ResolverError("小红书页面解析失败(平台反爬更新)，请下载后直接上传文件")


# ---------------- 抖音 ----------------

async def _resolve_douyin(url: str) -> dict:
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS,
                                 timeout=TIMEOUT) as c:
        r = await c.get(url)
        html = r.text
        final_url = str(r.url)

    # itemId
    m = re.search(r"/(?:video|note)/(\d+)", final_url) or \
        re.search(r"/(?:video|note)/(\d+)", html)
    if not m:
        raise ResolverError("抖音链接解析失败，未能定位作品ID")

    # 1) share 页 _ROUTER_DATA
    mdata = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})</script>",
                      html, re.S)
    if mdata:
        try:
            data = _to_json(mdata.group(1))
            stack = data.get("loaderData") or {}
            for k, v in stack.items():
                info = _find_douyin_item(v)
                if info:
                    return info
        except (json.JSONDecodeError, KeyError):
            pass

    # 2) iesdouyin iteminfo API
    try:
        async with httpx.AsyncClient(headers={"User-Agent": MOBILE_UA},
                                     timeout=TIMEOUT) as c:
            r = await c.get(
                "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
                params={"item_ids": m.group(1)})
            data = r.json()
            item = (data.get("item_list") or [{}])[0]
            play = ((item.get("video") or {}).get("play_addr") or {})
            urls = play.get("url_list") or []
            if urls:
                return {"platform": "douyin", "media_type": "video",
                        "url": urls[0],
                        "title": item.get("desc") or "抖音视频"}
    except Exception:
        pass

    raise ResolverError("抖音链接解析失败(平台反爬更新)，请下载后直接上传文件")


def _find_douyin_item(node, depth=0):
    if depth > 6:
        return None
    if isinstance(node, dict):
        if "video" in node and isinstance(node.get("video"), dict) and \
                (node["video"].get("play_addr") or node["video"].get("download_addr")):
            v = node["video"]
            addr = v.get("play_addr") or v.get("download_addr")
            urls = addr.get("url_list") or []
            if urls:
                return {"platform": "douyin", "media_type": "video",
                        "url": urls[0].replace("playwm", "play"),
                        "title": node.get("desc") or "抖音视频"}
        for v in node.values():
            found = _find_douyin_item(v, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_douyin_item(v, depth + 1)
            if found:
                return found
    return None


# ---------------- TikTok ----------------

async def _resolve_tiktok(url: str) -> dict:
    headers = {**HEADERS, "User-Agent": DESKTOP_UA}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers,
                                 timeout=TIMEOUT) as c:
        r = await c.get(url)
        html = r.text

    m = re.search(r'property="og:video"\s+content="([^"]+)"', html)
    if m:
        return {"platform": "tiktok", "media_type": "video",
                "url": m.group(1).replace("&amp;", "&"), "title": "TikTok视频"}

    m = re.search(r"__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{.*?\})</script>",
                  html, re.S)
    if m:
        try:
            data = _to_json(m.group(1))
            detail = (data.get("__DEFAULT_SCOPE__", {})
                          .get("webapp.video-detail", {}))
            item = detail.get("itemInfo") or {}
            video = item.get("video") or {}
            url_v = video.get("downloadAddr") or video.get("playAddr")
            if url_v:
                return {"platform": "tiktok", "media_type": "video",
                        "url": url_v, "title": item.get("desc") or "TikTok视频"}
        except (json.JSONDecodeError, KeyError):
            pass
    raise ResolverError("TikTok 链接解析失败，请下载后直接上传文件")


# ---------------- 下载 ----------------

async def download_media(url: str, dest: Path, referer: str = "") -> Path:
    """代理下载媒体文件(处理平台直链防盗链)。"""
    headers = {"User-Agent": MOBILE_UA}
    if referer:
        headers["Referer"] = referer
    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT,
                                 headers=headers) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(1024 * 256):
                    f.write(chunk)
    return dest
