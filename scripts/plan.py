"""편집 계획 초안 만들기: 받아쓰기 + 소리 크기 -> edit.json
사용: python plan.py <영상> <transcript.json> <edit.json>
쉬는 구간과 다시 말한 문장을 빼고, 자막 덩어리를 나눈 초안을 만든다.
초안은 Claude가 다듬은 뒤(오타, 강조, 영문, 장면, 효과음) make.py 로 렌더한다."""
import json, os, subprocess, sys, re
from difflib import SequenceMatcher
import numpy as np

PAD_IN, PAD_OUT = 0.07, 0.13   # 말 앞뒤 여유(초)
MIN_SIL = 0.30                 # 이보다 긴 침묵은 잘라낸다
MAX_CHARS, MAX_WORDS = 10, 3   # 자막 한 덩어리 크기


def speech_intervals(src):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    hop, win = 160, 400
    n = (len(a) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    db = 20 * np.log10(np.sqrt((a[idx] ** 2).mean(1)) + 1e-7)
    noise, peak = np.percentile(db, 10), np.percentile(db, 95)
    thr = max(noise + 9, peak - 30)
    on = db > thr
    out, i = [], 0
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            out.append([i * 0.01, j * 0.01 + 0.015])
            i = j
        else:
            i += 1
    merged = []
    for s, e in out:
        if merged and s - merged[-1][1] < MIN_SIL:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [m for m in merged if m[1] - m[0] >= 0.10], len(a) / 16000


def norm(t):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", t)


def main():
    src, tr_path, out_path = sys.argv[1:4]
    tr = json.load(open(tr_path, encoding="utf-8"))
    words = [w for s in tr["segments"] for w in s["words"]]
    iv, dur = speech_intervals(src)

    # 단어를 말소리 구간에 배정
    buckets = [[] for _ in iv]
    for w in words:
        best, score = None, -1e9
        for k, (s, e) in enumerate(iv):
            ov = min(e, w["e"]) - max(s, w["s"])
            if ov <= 0:
                ov = -min(abs(w["s"] - e), abs(w["s"] - s))
            if ov > score:
                best, score = k, ov
        buckets[best].append(w)

    clips = []
    for (s, e), ws in zip(iv, buckets):
        if not ws:
            continue  # 글자가 없는 소리(숨, 잡음)는 버린다
        clips.append({"start": round(max(0, s - PAD_IN), 3), "end": round(min(dur, e + PAD_OUT), 3),
                      "text": " ".join(w["w"] for w in ws), "words": ws, "keep": True})

    # 다시 말한 문장: 앞의 것을 버리고 마지막 것만 남긴다
    for i, c in enumerate(clips):
        a = norm(c["text"])
        if len(a) < 3:
            continue
        for j in range(i + 1, min(i + 4, len(clips))):
            b = norm(clips[j]["text"])
            if SequenceMatcher(None, a, b[: len(a) + 2]).ratio() >= 0.8:
                c["keep"] = False
                c["why"] = "다시 말함"
                break

    # 겹치는 구간 정리
    for p, q in zip(clips, clips[1:]):
        if p["end"] > q["start"]:
            mid = round((p["end"] + q["start"]) / 2, 3)
            p["end"], q["start"] = mid, mid

    out_clips, dropped = [], []
    for c in clips:
        if not c["keep"]:
            dropped.append({"start": c["start"], "end": c["end"], "text": c["text"], "why": c.get("why", "")})
            continue
        groups, cur = [], []
        for w in c["words"]:
            if cur and (len(cur) >= MAX_WORDS or len(norm("".join(x["w"] for x in cur)) + norm(w["w"])) > MAX_CHARS):
                groups.append(cur); cur = []
            cur.append(w)
        if cur:
            groups.append(cur)
        caps = []
        for k, g in enumerate(groups):
            st = c["start"] if k == 0 else min(max(g[0]["s"], c["start"]), c["end"] - 0.2)
            caps.append({"s": round(st, 3), "text": " ".join(x["w"] for x in g)})
        out_clips.append({"start": c["start"], "end": c["end"], "en": "", "captions": caps})

    plan = {
        "source": os.path.relpath(os.path.abspath(src), os.path.dirname(os.path.abspath(out_path))).replace("\\", "/"),
        "layout": "full",
        "brand": "",
        "sfx_volume": 0.55,
        "clips": out_clips,
        "scenes": [],
        "sfx": [{"at": out_clips[0]["start"], "name": "impact", "vol": 0.8}] if out_clips else [],
        "_dropped": dropped,
    }
    json.dump(plan, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(c["end"] - c["start"] for c in out_clips)
    print(f"원본 {dur:.1f}초 -> 편집 후 {total:.1f}초, 컷 {len(out_clips)}개")
    for c in clips:
        print(("  남김 " if c["keep"] else "  버림 ") + f"[{c['start']:6.2f}-{c['end']:6.2f}] {c['text']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
