"""把扣子工作流的输出转成本地任务文件。

用法：
    python from_coze.py coze_output.txt
    （把扣子结束节点返回的文本存成文件，或直接粘贴管道传入）

支持两种格式：
  1. 你现有工作流的输出：{"title": ..., "sentences": [{"chinese": ..., "english": ...}]}
     → 每句格言一行，拼成整段口播稿
  2. COZE.md 里定义的书单格式：{"title", "hook", "items", "tail", ...}
     → 原样进队列，一本书一张卡
"""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(BASE, "queue")


def strip_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if m:
        return m.group(1).strip()
    return text


def convert(raw: str) -> dict:
    data = json.loads(strip_fence(raw))

    if "items" in data or "script" in data or "hook" in data:
        job = data
    elif "sentences" in data:
        lines = []
        for s in data["sentences"]:
            if isinstance(s, dict):
                lines.append(s.get("chinese") or s.get("zh") or "")
            else:
                lines.append(str(s))
        job = {
            "title": data.get("title") or "书单分享",
            "script": "\n".join(x for x in lines if x),
        }
    else:
        raise ValueError("认不出格式：既没有 items 也没有 sentences。"
                         "扣子端请按 COZE.md 的 JSON 规范输出。")

    job.setdefault("id", "coze-" + time.strftime("%m%d-%H%M%S"))
    job.setdefault("title", "书单视频")
    return job


def main():
    if len(sys.argv) > 1:
        raw = open(sys.argv[1], encoding="utf-8").read()
    else:
        raw = sys.stdin.read()
    job = convert(raw)

    os.makedirs(QUEUE, exist_ok=True)
    p = os.path.join(QUEUE, job["id"] + ".json")
    json.dump(job, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已入队:", p)
    print("标题:", job.get("title"))
    print("接下来双击 run.bat，或运行 python scripts/build.py")


if __name__ == "__main__":
    main()
