"""편집할 영상을 찾는다.  사용: python find_video.py [폴더]
바탕화면의 '릴스' 폴더와 현재 폴더(또는 준 폴더)를 본다. 아직 릴스로 만들지 않은 최근 영상이 맨 위."""
import os, subprocess, sys

EXT = (".mp4", ".mov", ".m4v")
SKIP = ("완성", "릴스작업", "피부보정", "work", "node_modules")


def desktop():
    if os.name == "nt":
        try:
            p = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, timeout=20).stdout.strip()
            if p and os.path.isdir(p):
                return p
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def reels_folder():
    return os.path.join(desktop(), "릴스")


def videos(folder):
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        if root.count(os.sep) - folder.count(os.sep) > 2:
            dirs[:] = []
        out += [os.path.join(root, f) for f in files if f.lower().endswith(EXT)]
    return sorted(out, key=os.path.getmtime, reverse=True)


def done(path):
    """이미 릴스로 만든 영상인지"""
    name = os.path.splitext(os.path.basename(path))[0]
    return os.path.exists(os.path.join(os.path.dirname(path), "완성", name + "_릴스.mp4"))


if __name__ == "__main__":
    import time
    sys.stdout.reconfigure(encoding="utf-8")
    here = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    home = os.path.abspath(os.path.expanduser("~"))
    reels = reels_folder()
    os.makedirs(reels, exist_ok=True)
    found = videos(reels)
    if here not in (home, os.path.abspath(reels)):       # 홈 폴더 전체는 뒤지지 않는다
        found += [f for f in videos(here) if f not in found]
    found.sort(key=lambda f: (done(f), -os.path.getmtime(f)))   # 아직 안 만든 것, 그중 최근 것부터
    print("바탕화면 릴스 폴더:", reels)
    if not found:
        print("영상 없음 -> 사용자에게 바탕화면의 '릴스' 폴더에 영상을 넣어 달라고 한다")
    for f in found[:10]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(f)))
        print(("[이미 만듦] " if done(f) else "[새 영상]  ") + when + "  " + f)
