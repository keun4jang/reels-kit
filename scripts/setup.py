"""준비 확인: 필요한 도구가 있는지 보고, 파이썬 패키지는 바로 설치한다.  사용: python setup.py"""
import importlib, shutil, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8")
ok = True
for tool in ("ffmpeg", "ffprobe"):
    if shutil.which(tool):
        print(f"[확인] {tool}")
    else:
        ok = False
        print(f"[없음] {tool}  ->  Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg (설치 후 터미널 다시 열기)")
need = [("numpy", "numpy"), ("PIL", "pillow"), ("faster_whisper", "faster-whisper"), ("cv2", "opencv-python")]
missing = []
for mod, pkg in need:
    try:
        importlib.import_module(mod)
        print(f"[확인] {pkg}")
    except Exception:
        missing.append(pkg)
if missing:
    print("설치 중:", " ".join(missing))
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *missing])
    if r.returncode != 0:
        ok = False
        print("[실패] pip 설치. 직접 실행: python -m pip install " + " ".join(missing))
    else:
        print("[확인] 패키지 설치 완료")
try:   # 영상을 넣을 폴더를 바탕화면에 만들어 둔다
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from find_video import reels_folder
    os.makedirs(reels_folder(), exist_ok=True)
    print("[확인] 영상 넣는 폴더:", reels_folder())
except Exception as e:
    print("[참고] 바탕화면에 '릴스' 폴더를 만들지 못했습니다:", e)
print("준비 완료" if ok else "준비 안 됨: 위 [없음]/[실패] 항목을 해결한 뒤 다시 실행")
sys.exit(0 if ok else 1)
