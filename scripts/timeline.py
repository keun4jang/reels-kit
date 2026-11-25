"""편집 계획(edit.json)의 원본 시간 <-> 완성본 시간 변환"""
import json

W, H, FPS = 1080, 1920, 30
SPK_Y = 980                 # 분할 화면에서 화자 영역이 시작하는 높이
SPK_H = H - SPK_Y


def speaker_area(plan):
    """화자가 들어갈 영역 (세로 시작 위치, 높이). full 이면 화면 전체"""
    return (0, H) if plan.get("layout", "split") == "full" else (SPK_Y, SPK_H)


def load(path):
    plan = json.load(open(path, encoding="utf-8"))
    t = 0.0
    for c in plan["clips"]:
        # 프레임 단위로 맞춰 영상과 그래픽이 어긋나지 않게 한다
        n = max(1, round((c["end"] - c["start"]) * FPS))
        c["dur"] = n / FPS
        c["out"] = t
        t += c["dur"]
    plan["total"] = t
    return plan


def to_out(plan, src_t):
    """원본 시간 -> 완성본 시간 (남긴 구간 안이 아니면 가장 가까운 경계)"""
    best, bd = 0.0, 1e9
    for c in plan["clips"]:
        if c["start"] - 1e-6 <= src_t <= c["end"] + 1e-6:
            return c["out"] + min(src_t - c["start"], c["dur"])
        for edge, o in ((c["start"], c["out"]), (c["end"], c["out"] + c["dur"])):
            if abs(src_t - edge) < bd:
                best, bd = o, abs(src_t - edge)
    return best
