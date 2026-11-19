"""从 Pexels 拉取免版权竖屏素材，填满 assets/clips 素材池。

1. 到 https://www.pexels.com/api/ 免费注册，拿到 API Key
2. 设置环境变量 PEXELS_KEY，或直接改下面的 KEY
3. python fetch_stock.py "书籍 阅读" 20
   （关键词 想要的条数），素材会存到 assets/clips/
"""
import json
import os
import sys
import urllib.parse
import urllib.request

from utils import ensure_dir

KEY = os.environ.get("PEXELS_KEY", "")
CLIPS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "clips")


def fetch(query: str, count: int = 20):
    if not KEY:
        print("请先设置 PEXELS_KEY（https://www.pexels.com/api/ 免费申请）")
        print('  PowerShell:  $env:PEXELS_KEY="你的key"')
        print('  CMD:         set PEXELS_KEY=你的key')
        return
    ensure_dir(CLIPS)
    per = min(count, 80)
    url = ("https://api.pexels.com/videos/search?query=%s&per_page=%d"
           "&orientation=portrait" % (urllib.parse.quote(query), per))
    req = urllib.request.Request(url, headers={"Authorization": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    saved = 0
    for v in data.get("videos", []):
        files = v.get("video_files", [])
        best = None
        for f in files:
            if f.get("width", 0) and 700 <= f["width"] <= 1200 \
                    and f.get("file_type") == "video/mp4":
                if best is None or f["width"] < best["width"]:
                    best = f
        if not best:
            continue
        name = "pexels_%d.mp4" % v["id"]
        dst = os.path.join(CLIPS, name)
        if os.path.exists(dst):
            continue
        try:
            urllib.request.urlretrieve(best["link"], dst)
            saved += 1
            print("已下载", name)
        except Exception as e:
            print("跳过", name, e)
        if saved >= count:
            break
    print("\n本次新增 %d 条，素材池共 %d 条" % (saved, len(os.listdir(CLIPS))))


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "books reading"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    fetch(q, n)
