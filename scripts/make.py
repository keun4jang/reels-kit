"""edit.json -> 완성 영상.  사용: python make.py <edit.json> <완성.mp4> [--still 초,초,...]
--still 을 주면 영상을 만들지 않고 그 시각의 장면만 그림으로 뽑아 확인한다."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    edit, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    work = os.path.dirname(edit)
    base = os.path.join(work, "base.mp4")
    stamp = os.path.join(work, "base.stamp")
    # 컷(clips)·화면 구성이 그대로면 느린 1단계를 다시 하지 않는다
    import json
    plan = json.load(open(edit, encoding="utf-8"))
    sig = json.dumps([plan.get("source"), plan.get("layout"), plan.get("panel_color"),
                      [[c["start"], c["end"], c.get("type"), c.get("tight"), c.get("zoom")] for c in plan["clips"]]])
    if not (os.path.exists(base) and os.path.exists(stamp) and open(stamp, encoding="utf-8").read() == sig):
        print("1/2 컷 이어붙이는 중...")
        subprocess.run([sys.executable, os.path.join(HERE, "base.py"), edit, base], check=True)
        open(stamp, "w", encoding="utf-8").write(sig)
    if len(sys.argv) > 3 and sys.argv[3] == "--still":
        subprocess.run([sys.executable, os.path.join(HERE, "gfx.py"), edit, base, "--still", sys.argv[4],
                        os.path.join(work, "stills")], check=True)
        print("장면 그림:", os.path.join(work, "stills"))
        return
    print("2/2 그래픽·자막·효과음 얹는 중...")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "gfx.py"), edit, base, out], check=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
