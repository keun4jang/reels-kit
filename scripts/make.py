"""edit.json -> 완성 영상.
사용: python make.py <edit.json> <완성.mp4>
확인: python make.py <edit.json> <완성.mp4> --still scenes        (장면마다 그림 2장)
      python make.py <edit.json> <완성.mp4> --still 1.0,5.0,12.0  (완성본 기준 초)"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def say(msg):
    print(msg, flush=True)


def main():
    args = sys.argv[1:]
    still = None
    if "--still" in args:
        i = args.index("--still")
        still = args[i + 1] if i + 1 < len(args) else "scenes"
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    edit = os.path.abspath(args[0])
    work = os.path.dirname(edit)
    out = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(work, "out.mp4")
    base, stamp = os.path.join(work, "base.mp4"), os.path.join(work, "base.stamp")
    plan = json.load(open(edit, encoding="utf-8"))
    # 컷과 화면 잡는 값이 그대로면 느린 1단계를 다시 하지 않는다
    sig = json.dumps([plan.get("source"), plan.get("layout"), plan.get("panel_color"), plan.get("look"),
                      [[c["start"], c["end"], c.get("type"), c.get("tight"), c.get("zoom")] for c in plan["clips"]]])
    if not (os.path.exists(base) and os.path.exists(stamp) and open(stamp, encoding="utf-8").read() == sig):
        say("1/2 컷 이어붙이는 중...")
        subprocess.run([sys.executable, os.path.join(HERE, "base.py"), edit, base], check=True)
        look = plan.get("look") or {}
        skin = float(look.get("skin", 0) or 0)
        extra = []          # 화장: 입술색, 블러셔, 톤업, 선글라스
        for key in ("lip", "blush", "tone", "eye", "glasses"):
            if look.get(key):
                extra += ["--" + key, str(look[key])]
        if skin > 0 or extra:   # 피부만 골라 보정 (눈·머리카락은 그대로)
            say("    피부 보정 중...")
            pre = os.path.join(work, "base_pre.mp4")
            os.replace(base, pre)
            subprocess.run([sys.executable, os.path.join(HERE, "skin.py"), pre, base, "--strength", str(skin), *extra], check=True)
            os.remove(pre)
        open(stamp, "w", encoding="utf-8").write(sig)
    if still:
        subprocess.run([sys.executable, os.path.join(HERE, "gfx.py"), edit, base, "--still", still,
                        os.path.join(work, "stills")], check=True)
        say("장면 그림(파일 이름의 숫자는 완성본 기준 초): " + os.path.join(work, "stills"))
        return
    say("2/2 그래픽·자막·효과음 얹는 중...")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "gfx.py"), edit, base, out], check=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
