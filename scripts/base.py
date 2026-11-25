"""1단계 렌더: 컷 이어붙이기 + 얼굴 따라 화면 잡기 + 목소리 정리 -> base.mp4
사용: python base.py <edit.json> <base.mp4>"""
import os, subprocess, sys
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # 얼굴 인식 경고 줄을 숨긴다
import numpy as np
import timeline as TL

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")


def probe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,color_transfer:stream_side_data=rotation", "-of", "default=nw=1", src],
                         capture_output=True, text=True).stdout
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    w, h = int(d["width"]), int(d["height"])
    if abs(int(float(d.get("rotation", 0)))) in (90, 270):
        w, h = h, w
    return w, h, d.get("color_transfer", "") in ("arib-std-b67", "smpte2084")


def find_face(src, t0, t1, sw, sh):
    """구간 안 몇 장면에서 얼굴을 찾아 (x, y, w, h) 중앙값을 돌려준다. 없으면 None"""
    try:
        import cv2
        dw, dh = 270, int(270 * sh / sw / 2) * 2
        det = cv2.FaceDetectorYN.create(os.path.join(KIT, "assets", "models", "yunet.onnx"), "", (dw, dh), 0.6)
    except Exception:
        return None
    found = []
    for t in np.linspace(t0 + 0.1, max(t0 + 0.1, t1 - 0.1), 4):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf",
                              f"scale={dw}:{dh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
        if len(raw) != dw * dh * 3:
            continue
        _, f = det.detect(np.frombuffer(raw, np.uint8).reshape(dh, dw, 3))
        if f is not None:
            found.append(max(f, key=lambda r: r[2] * r[3])[:4] * (sw / dw))
    return np.median(np.array(found), axis=0) if found else None


def main():
    plan_path, out = sys.argv[1], sys.argv[2]
    plan = TL.load(plan_path)
    src = plan["source"]
    if not os.path.isabs(src):
        src = os.path.join(os.path.dirname(os.path.abspath(plan_path)), src)
    sw, sh, hdr = probe(src)
    tm = TONEMAP if hdr else "format=yuv420p,"
    bg = plan.get("panel_color", "F2EFE9")
    spk_y, spk_h = TL.speaker_area(plan)
    full = spk_h == TL.H
    args, fc, tight = ["ffmpeg", "-y", "-v", "error", "-nostats"], [], False
    for i, c in enumerate(plan["clips"]):
        args += ["-ss", f"{c['start']:.3f}", "-t", f"{c['dur'] + 0.2:.3f}", "-i", src]
        n = round(c["dur"] * TL.FPS)
        if c.get("type") == "raw":   # 편집 전 원본 그대로
            v = f"[{i}:v]fps={TL.FPS},{tm}scale={TL.W}:{TL.H}:force_original_aspect_ratio=increase,crop={TL.W}:{TL.H}"
        else:
            ar = TL.W / spk_h
            face = find_face(src, c["start"], c["end"], sw, sh)
            tight = c.get("tight", not tight)   # 컷마다 넓게/좁게 번갈아
            if face is None:
                cw = sw * (0.86 if tight else 1.0); cx, cy = sw / 2, sh * 0.38
            else:
                fx, fy, fw, fh = face
                cw = min(sw, fw * (4.4 if full else 3.3)) * (0.86 if tight else 1.0) / c.get("zoom", 1.0)
                cx, cy = fx + fw / 2, fy + fh / 2
            cw = min(sw, max(360, cw)); ch = min(sh, cw / ar); cw = ch * ar
            x = min(max(0, cx - cw / 2), sw - cw)
            y = min(max(0, cy - ch * (0.36 if full else 0.44)), sh - ch)
            cw, ch, x, y = (int(round(v / 2)) * 2 for v in (cw, ch, x, y))
            v = f"[{i}:v]fps={TL.FPS},crop={cw}:{ch}:{x}:{y},{tm}scale={TL.W}:{spk_h}:flags=lanczos"
            if not full:
                v += f",pad={TL.W}:{TL.H}:0:{spk_y}:color=0x{bg}"
        fc.append(f"{v},trim=end_frame={n},setpts=PTS-STARTPTS,setsar=1[v{i}]")
        fc.append(f"[{i}:a]atrim=end={c['dur']:.4f},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"aformat=channel_layouts=stereo,"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(0, c['dur'] - 0.03):.3f}:d=0.03[a{i}]")
    k = len(plan["clips"])
    fc.append("".join(f"[v{i}][a{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=1[v][ac]")
    fc.append("[ac]highpass=f=80,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120,"
              "loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000[a]")
    args += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "14", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-c:a", "aac", "-b:a", "256k", out]
    subprocess.run(args, check=True)
    print(f"기본 영상 완료: {plan['total']:.1f}초")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
