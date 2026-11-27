"""피부 보정: 얼굴을 찾아 피부만 부드럽게 한다. 눈, 눈썹, 입술, 머리카락, 배경은 그대로 둔다.
사용: python skin.py <영상> [출력.mp4] [--strength 0.6]
확인: python skin.py <영상> --still 3.0 [그림.jpg]      (3.0초 장면의 전/후 비교 그림)
strength 는 0~1 (0.3 은은하게, 0.6 기본, 0.9 강하게, 0 이면 피부 보정 없이 화장만)
화장: --lip rose|coral|pink|red[:진하기]   --blush 0~2   --tone 0~1   --eye 0~2(눈 화장)   --eye-color brown|plum|pink   --glasses black|brown
시간표: --timeline 시간표.json  ([{"at": 초, "fade": 0.2, "skin": 0.6, "lip": "pink", "blush": 0.6, "wipe": 0.5, "glasses": "black"}, ...])"""
import os, subprocess, sys
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import numpy as np

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
WORK = 240          # 얼굴 폭을 이 크기(픽셀)로 줄여서 계산한다: 빠르고, 아주 고운 결은 건드리지 않게 된다


def probe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate,color_transfer:stream_side_data=rotation:format=duration",
                          "-of", "default=nw=1", src], capture_output=True, text=True).stdout
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    w, h = int(d["width"]), int(d["height"])
    if abs(int(float(d.get("rotation", 0)))) in (90, 270):
        w, h = h, w
    a, b = (d.get("avg_frame_rate", "30/1").split("/") + ["1"])[:2]
    fps = float(a) / float(b) if float(b) else 30.0
    fps = min(60.0, max(1.0, fps or 30.0))
    return w, h, fps, d.get("color_transfer", "") in ("arib-std-b67", "smpte2084"), float(d.get("duration", 0) or 0)


LOOK = {"lip": None, "lip_amt": 0.45, "blush": 0.0, "tone": 0.0, "eye": 0.0, "glasses": None}
LIPS = {"rose": (190, 85, 100), "coral": (235, 105, 90), "pink": (235, 100, 140), "red": (200, 35, 55)}   # RGB
SHADES = {"black": ((30, 26, 26), (96, 84, 80)), "brown": ((20, 34, 62), (60, 110, 170))}      # 렌즈 위/아래 색 BGR
EYE_COLORS = {"brown": (70, 85, 135), "plum": (150, 80, 170), "pink": (160, 130, 235)}       # 눈두덩 색 BGR
_shade_cache = {}


def shade_art(style, cv2):
    """선글라스 그림 (기준 크기: 두 눈이 (400,300)과 (800,300)에 오게). BGR, 투명도"""
    if style in _shade_cache:
        return _shade_cache[style]
    top, bot = SHADES.get(style, SHADES["black"])
    Hc, Wc = 600, 1200
    lens = np.zeros((Hc, Wc), np.uint8)
    rim = np.zeros((Hc, Wc), np.uint8)
    for cx in (400, 800):               # 동그란 알 두 개, 알 사이는 넉넉히 띄운다
        cv2.circle(rim, (cx, 318), 194, 255, -1, cv2.LINE_AA)
        cv2.circle(lens, (cx, 318), 152, 255, -1, cv2.LINE_AA)
    cv2.ellipse(rim, (600, 300), (40, 34), 0, 180, 360, 255, 22, cv2.LINE_AA)      # 코걸이
    grad = np.linspace(0, 1, Hc, dtype=np.float32)[:, None, None]
    col = np.array(top, np.float32) * (1 - grad) + np.array(bot, np.float32) * grad
    col = np.repeat(col, Wc, axis=1)
    shine = np.zeros((Hc, Wc), np.uint8)                                            # 비스듬한 반사광
    for cx in (400, 800):
        cv2.fillPoly(shine, [np.array([[cx - 120, 330], [cx - 30, 200], [cx + 20, 200], [cx - 70, 330]])], 255)
    shine = cv2.GaussianBlur(shine, (0, 0), 14).astype(np.float32) / 255 * (lens > 0)
    col = col + shine[..., None] * 70
    l, rm = lens.astype(np.float32) / 255, rim.astype(np.float32) / 255
    frame_only = np.clip(rm - l, 0, 1)
    col = col * (1 - frame_only[..., None]) + np.array((14, 14, 16), np.float32) * frame_only[..., None]
    alpha = np.maximum(l * 0.93, frame_only)
    _shade_cache[style] = (col, alpha)
    return _shade_cache[style]


def sunglasses(frame, face, cv2, mesh=None, L=None):
    L = L or LOOK
    """두 눈 위치에 맞춰 선글라스를 씌운다 (기울기와 크기를 따라간다)"""
    H, W = frame.shape[:2]
    a, b = sorted((face[4:6], face[6:8]), key=lambda p: p[0])
    d = float(np.hypot(*(b - a)))
    if d < 8:
        return
    mid = (a + b) / 2
    x0, x1 = int(max(0, mid[0] - 1.7 * d)), int(min(W, mid[0] + 1.7 * d))
    y0, y1 = int(max(0, mid[1] - 1.1 * d)), int(min(H, mid[1] + 1.1 * d))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return
    n = np.array([-(b - a)[1], (b - a)[0]])                  # 눈 사이 선에 수직인 방향
    src = np.float32([[400, 300], [800, 300], [400, 700]])
    dst = (np.array([a, b, a + n], np.float64) - (x0, y0)).astype(np.float32)
    amt = float(L.get("glasses_amt", 1.0))
    if amt <= 0.01:
        return
    dst[:, 1] -= (1 - amt) ** 2 * 2.4 * d                  # 위에서 내려와 얹힌다
    M = cv2.getAffineTransform(src, dst)
    if mesh is not None:        # 안경다리: 렌즈 바깥 끝에서 귀 쪽으로
        ears = sorted((mesh[127], mesh[356]), key=lambda p: p[0])
        for cpt, ear in (((218, 270), ears[0]), ((982, 270), ears[1])):
            p0 = M @ np.array([cpt[0], cpt[1], 1.0]) + (x0, y0)
            if abs(ear[0] - p0[0]) > 0.04 * d and (ear[0] - p0[0]) * (p0[0] - mid[0]) > 0:
                if amt > 0.97:
                    cv2.line(frame, (int(p0[0]), int(p0[1])), (int(ear[0]), int(ear[1] - 0.05 * d)), (16, 14, 14),
                             max(2, int(d * 0.045)), cv2.LINE_AA)
    col, alpha = shade_art(L["glasses"], cv2)
    size = (x1 - x0, y1 - y0)
    col = cv2.warpAffine(col, M, size, flags=cv2.INTER_AREA)
    al = cv2.warpAffine(alpha, M, size, flags=cv2.INTER_AREA)[..., None]
    al = al * min(1.0, amt * 2.5)
    roi = frame[y0:y1, x0:x1]
    roi[:] = np.clip(roi * (1 - al) + col * al, 0, 255).astype(np.uint8)


OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
        150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIP_OUT = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LIP_IN = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
EYES = ([33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
        [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466])
LIDS = ([33, 246, 161, 160, 159, 158, 157, 173, 133], [263, 466, 388, 387, 386, 385, 384, 398, 362])   # 눈꼬리 -> 앞머리
BROWS = ([70, 63, 105, 66, 107, 55, 65, 52, 53, 46], [300, 293, 334, 296, 336, 285, 295, 282, 283, 276])


class Faces:
    """프레임마다 얼굴을 찾는다. (값 14개, 얼굴 윤곽 점 478개 또는 None) 의 목록을 돌려준다.
    값 14개 = 얼굴 상자 x,y,w,h + 오른눈, 왼눈, 코, 입 오른쪽, 입 왼쪽 (화면에서 왼쪽에 보이는 것이 먼저)"""
    def __init__(self, w, h):
        import cv2
        self.cv2, self.w, self.h, self.n = cv2, w, h, 0
        self.mesh, self.last = None, []
        try:        # 정밀 인식: 입술·눈 윤곽까지 잡는다
            import mediapipe as mp
            V = mp.tasks.vision
            model = open(os.path.join(KIT, "assets", "models", "face_landmarker.task"), "rb").read()
            self.mp = mp
            self.mesh = V.FaceLandmarker.create_from_options(V.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=model), running_mode=V.RunningMode.VIDEO, num_faces=4))
        except Exception:
            pass
        self.k = 320 / max(w, h)
        self.size = (max(2, int(w * self.k)), max(2, int(h * self.k)))
        self.det = cv2.FaceDetectorYN.create(os.path.join(KIT, "assets", "models", "yunet.onnx"), "", self.size, 0.6)
        self.prev = []      # [값 14개, 못 찾은 횟수]

    def find(self, frame):
        if self.mesh is not None:
            self.n += 1
            rgb = np.ascontiguousarray(frame[..., ::-1])
            res = self.mesh.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), self.n * 33)
            out, new_last = [], []
            for lm in res.face_landmarks:
                p = np.array([(q.x * self.w, q.y * self.h) for q in lm], np.float32)
                old = self.last[len(out)] if len(out) < len(self.last) else None
                if old is not None:     # 가만히 있을 때의 잔떨림만 누른다 (빨리 움직이면 그대로 따라간다)
                    span = float(p[:, 0].max() - p[:, 0].min()) + 1e-3
                    move = np.hypot(*(p - old).T)[:, None] / span
                    k_ = np.clip(move / 0.012, 0.35, 1.0)
                    p = (old + (p - old) * k_).astype(np.float32)
                new_last.append(p)
                lo, hi = p[OVAL].min(0), p[OVAL].max(0)
                if hi[0] - lo[0] < 24:
                    continue
                eyes = sorted((p[EYES[0]].mean(0), p[EYES[1]].mean(0)), key=lambda q: q[0])
                mouth = sorted((p[61], p[291]), key=lambda q: q[0])
                out.append((np.concatenate([lo, hi - lo, eyes[0], eyes[1], p[1], mouth[0], mouth[1]]), p))
            self.last = new_last
            return out
        return [(v, None) for v in self.find_simple(frame)]

    def find_simple(self, frame):
        cv2 = self.cv2
        _, f = self.det.detect(cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA))
        now = [r[:14] / self.k for r in f] if f is not None else []
        now = [r for r in now if r[2] > 24][:6]
        out, used = [], set()
        for r in now:
            c = r[:2] + r[2:4] / 2
            best = None
            for i, (p, _) in enumerate(self.prev):
                if i not in used and np.hypot(*(p[:2] + p[2:4] / 2 - c)) < 0.5 * r[2]:
                    best = i
                    break
            if best is not None:
                used.add(best)
                r = 0.55 * r + 0.45 * self.prev[best][0]
            out.append([r, 0])
        for i, (p, miss) in enumerate(self.prev):     # 잠깐 놓친 얼굴은 몇 프레임 더 유지
            if i not in used and miss < 8:
                out.append([p, miss + 1])
        self.prev = out
        return [p for p, _ in out]


def fill(mask, pts, idx, val, grow=0):
    """윤곽 점으로 둘러싼 곳을 칠한다 (grow 만큼 바깥으로 넓힘)"""
    import cv2
    poly = [np.round(pts[idx]).astype(np.int32)]
    cv2.fillPoly(mask, poly, val)
    if grow > 0:
        cv2.polylines(mask, poly, True, val, int(grow) * 2)


def retouch(frame, face, strength, cv2, show_mask=False, L=None):
    """얼굴 하나의 피부를 보정한다 (frame 을 직접 고친다)"""
    L = L or LOOK
    face, mesh = face
    H, W = frame.shape[:2]
    x, y, w, h = face[:4]
    if mesh is not None:        # 정밀 인식의 상자는 이마 끝~턱 끝이라 조금 줄여서 맞춘다
        x, y, w, h = x + 0.06 * w, y + 0.18 * h, 0.88 * w, 0.82 * h
    x0, x1 = int(max(0, x - 0.45 * w)), int(min(W, x + 1.45 * w))
    y0, y1 = int(max(0, y - 0.5 * h)), int(min(H, y + 1.55 * h))
    if x1 - x0 < 16 or y1 - y0 < 16:
        return
    roi = frame[y0:y1, x0:x1]
    k = min(1.0, (WORK * 1.5 if L["eye"] else WORK) / w)
    sw, sh = max(8, int((x1 - x0) * k)), max(8, int((y1 - y0) * k))
    small = cv2.resize(roi, (sw, sh), interpolation=cv2.INTER_AREA)
    fw, fh = w * k, h * k
    pts = ((face[4:14].reshape(5, 2) - (x0, y0)) * k)        # 오른눈, 왼눈, 코, 입 오른쪽, 입 왼쪽
    eye_r, eye_l, nose, mo_r, mo_l = pts
    mp_ = None if mesh is None else (mesh - (x0, y0)) * k

    # 1) 피부색 배우기: 양 볼과 코 주변 색을 본보기로 삼는다
    ycc = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    samp = np.zeros((sh, sw), np.uint8)
    for a, b in ((eye_r, mo_r), (eye_l, mo_l)):
        c = a * 0.45 + b * 0.55
        cv2.circle(samp, (int(c[0]), int(c[1])), max(2, int(fw * 0.09)), 255, -1)
    cv2.circle(samp, (int(nose[0]), int(nose[1] - fh * 0.06)), max(2, int(fw * 0.06)), 255, -1)
    px = ycc[samp > 0]
    if len(px) < 12:
        return
    mean = np.median(px, axis=0)
    dev = px - mean
    cov = dev[:, 1:].T @ dev[:, 1:] / len(px) + np.eye(2) * 6.0
    d = ycc[..., 1:] - mean[1:]
    inv = np.linalg.inv(cov)
    d2 = d[..., 0] ** 2 * inv[0, 0] + 2 * d[..., 0] * d[..., 1] * inv[0, 1] + d[..., 1] ** 2 * inv[1, 1]
    color = np.clip(1.0 - (np.sqrt(d2) - 2.2) / 1.6, 0, 1)
    ystd = max(18.0, float(dev[:, 0].std()))
    gray = float(ycc[..., 1:].std()) < 1.5       # 흑백 영상은 색으로 못 가리니 밝기를 더 엄격하게 본다
    lim, ystd = (1.5, max(12.0, float(dev[:, 0].std()))) if gray else (3.2, ystd)
    luma = np.clip(1.0 - (np.abs(ycc[..., 0] - mean[0]) / ystd - lim) / 1.5, 0, 1)

    # 2) 얼굴과 목 근처로 제한하고, 눈·눈썹·입은 뺀다
    geom = np.zeros((sh, sw), np.float32)
    cx, cy = (x + w / 2 - x0) * k, (y + h * 0.52 - y0) * k
    cv2.ellipse(geom, (int(cx), int(cy)), (int(fw * 0.78), int(fh * 0.86)), 0, 0, 360, 1.0, -1)
    keep = np.ones((sh, sw), np.float32)
    for e in (eye_r, eye_l):
        cv2.ellipse(keep, (int(e[0]), int(e[1])), (int(fw * 0.15), int(fh * 0.075)), 0, 0, 360, 0.0, -1)
        cv2.ellipse(keep, (int(e[0]), int(e[1] - fh * 0.115)), (int(fw * 0.19), int(fh * 0.05)), 0, 0, 360, 0.0, -1)
    mc, mw = (mo_r + mo_l) / 2, float(np.hypot(*(mo_l - mo_r)))
    cv2.ellipse(keep, (int(mc[0]), int(mc[1])), (int(mw * 0.68), int(fh * 0.085)), 0, 0, 360, 0.0, -1)
    if mp_ is not None:
        geom[:] = 0
        fill(geom, mp_, OVAL, 1.0)
        keep[:] = 1
        for idx in EYES + BROWS:
            fill(keep, mp_, idx, 0.0, fw * 0.02)
        fill(keep, mp_, LIP_OUT, 0.0, fw * 0.012)
    g = max(3, int(fw * 0.035)) | 1
    mask = color * luma * cv2.GaussianBlur(geom, (0, 0), fw * 0.06) * cv2.GaussianBlur(keep, (g, g), 0)
    mask = cv2.GaussianBlur(mask, (g, g), 0)

    # 3) 윤곽은 남기고 잔결만 지운 뒤, 그 차이만 원본에 더한다 (모공 같은 고운 결은 원본 그대로 남는다)
    img = small.astype(np.float32)
    r = max(2, int(fw * (0.022 + 0.02 * strength)))
    soft = img
    for eps in ((7 + 13 * strength) ** 2, (5 + 8 * strength) ** 2):     # 두 번: 큰 얼룩, 그다음 잔결
        m_i = cv2.blur(soft, (2 * r + 1, 2 * r + 1))
        var = cv2.blur(soft * soft, (2 * r + 1, 2 * r + 1)) - m_i * m_i
        a = var / (var + eps)                  # 윤곽(변화가 큰 곳)은 1에 가까워 그대로 남는다
        b = m_i - a * m_i
        soft = cv2.blur(a, (2 * r + 1, 2 * r + 1)) * soft + cv2.blur(b, (2 * r + 1, 2 * r + 1))
        r = max(1, r // 2)
    delta = (soft - img) * (mask * min(1.0, 0.35 + 0.75 * strength))[..., None]
    if L["tone"] > 0:        # 톤업: 피부만 살짝 밝게
        delta += (mask * L["tone"] * 16)[..., None]
    if L["blush"] > 0:       # 블러셔: 양 볼에 번지는 분홍
        blob = np.zeros((sh, sw), np.float32)
        for e, m_ in ((eye_r, mo_r), (eye_l, mo_l)):
            c = e * 0.45 + m_ * 0.55
            c[0] += np.sign(c[0] - cx) * fw * 0.07
            cv2.circle(blob, (int(c[0]), int(c[1])), max(2, int(fw * 0.10)), 1.0, -1)
        blob = cv2.GaussianBlur(blob, (0, 0), fw * 0.085) * mask * L["blush"] * 0.5
        delta += (np.array((135, 120, 245), np.float32) - img) * blob[..., None]
    lip_mask = None
    if L["lip"]:             # 입술색: 입 주변에서 피부보다 붉은 곳만 골라 색을 입힌다 (치아, 입 안은 뺀다)
        lg = np.zeros((sh, sw), np.float32)
        ang = float(np.degrees(np.arctan2(*(mo_l - mo_r)[::-1])))
        cv2.ellipse(lg, (int(mc[0]), int(mc[1])), (int(mw * 0.66), int(mw * 0.36)), ang, 0, 360, 1.0, -1)
        red = (ycc[..., 1] - mean[1]) + 1.2 * (ycc[..., 2] - mean[2])      # 입술은 피부보다 붉고 푸른 기가 돈다
        lip_mask = np.clip((red - 3.5) / 4.5, 0, 1) * np.clip((ycc[..., 0] - 45) / 30, 0, 1)
        lip_mask = cv2.GaussianBlur(lip_mask * cv2.GaussianBlur(lg, (0, 0), mw * 0.06), (0, 0), max(0.8, fw * 0.006))
        if mp_ is not None:
            lip_mask = np.zeros((sh, sw), np.float32)
            fill(lip_mask, mp_, LIP_OUT, 1.0)
            fill(lip_mask, mp_, LIP_IN, 0.0)
            lip_mask = cv2.GaussianBlur(lip_mask, (0, 0), max(0.8, fw * 0.008)) * np.clip((ycc[..., 0] - 40) / 30, 0, 1)
        rgb = LIPS.get(L["lip"], LIPS["rose"])
        tgt = cv2.cvtColor(np.uint8([[rgb[::-1]]]), cv2.COLOR_BGR2YCrCb)[0, 0].astype(np.float32)
        amt = L["lip_amt"]
        y2 = ycc.copy()
        y2[..., 0] *= 1 - 0.10 * amt
        y2[..., 1:] += (tgt[1:] - y2[..., 1:]) * (0.75 * amt)
        tint = cv2.cvtColor(np.clip(y2, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR).astype(np.float32)
        delta += (tint - img) * lip_mask[..., None]
    if L["eye"] > 0 and mp_ is not None:      # 눈 화장: 속눈썹 선에서 위로 옅어지는 음영 + 아이라인
        shade, line = np.zeros((sh, sw), np.float32), np.zeros((sh, sw), np.float32)
        for idx, bidx in zip(LIDS, BROWS):
            u = mp_[idx]
            ax = u[-1] - u[0]
            ew = float(np.hypot(*ax))
            if ew < 6:
                continue
            n = np.array([ax[1], -ax[0]]) / ew
            n = -n if n[1] > 0 else n                         # 눈썹 쪽(위)
            reach = float(np.dot(mp_[bidx].mean(0) - u.mean(0), n))       # 눈꺼풀에서 눈썹까지
            reach = min(max(reach, ew * 0.25), ew * 0.8) * 0.62
            bulge = np.sin(np.linspace(0.12, np.pi - 0.12, len(u)))[:, None] ** 0.8
            for step in range(1, 7):                          # 여러 겹: 속눈썹 쪽이 가장 진하다
                top = u + n * reach * (step / 6) * bulge
                layer = np.zeros((sh, sw), np.float32)
                cv2.fillPoly(layer, [np.round(np.vstack([u, top[::-1]])).astype(np.int32)], 1.0, cv2.LINE_AA)
                shade += layer / 6
            wing = u[0] + (u[0] - u[2]) * 0.4 + n * ew * 0.05
            cv2.polylines(line, [np.round(np.vstack([wing, u])).astype(np.int32)], False, 1.0, max(1, int(round(ew * 0.035))), cv2.LINE_AA)
        ew_ = max(6.0, fw * 0.2)
        shade = cv2.GaussianBlur(shade, (0, 0), ew_ * 0.07) * min(0.85, 0.42 * L["eye"])
        base_ = np.clip(img + delta, 0, 255).astype(np.uint8)       # 색만 옮기고 밝기는 조금만 낮춰 피부 결을 살린다
        y3 = cv2.cvtColor(base_, cv2.COLOR_BGR2YCrCb).astype(np.float32)
        tgt = cv2.cvtColor(np.uint8([[L.get("eye_color") or (70, 85, 135)]]), cv2.COLOR_BGR2YCrCb)[0, 0].astype(np.float32)
        y3[..., 0] *= 1 - 0.22 * shade
        y3[..., 1:] += (tgt[1:] - y3[..., 1:]) * shade[..., None]
        delta = cv2.cvtColor(np.clip(y3, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR).astype(np.float32) - img
        line = cv2.GaussianBlur(line, (0, 0), 0.7) * min(0.85, 0.5 * L["eye"] + 0.2)
        delta = delta * (1 - line[..., None]) + (np.array((22, 22, 30), np.float32) - img) * line[..., None]
    if show_mask:
        delta = np.dstack([mask * -60, mask * 60, mask * -60])
        if lip_mask is not None:
            delta += np.dstack([lip_mask * 90, lip_mask * -60, lip_mask * 90])
    if k < 1.0:
        delta = cv2.resize(delta, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    roi[:] = np.clip(roi.astype(np.float32) + delta, 0, 255).astype(np.uint8)
    if L["glasses"] and L.get("glasses_amt", 1.0) > 0.01:
        sunglasses(frame, face, cv2, mesh, L)


NUM = {"skin": None, "lip_amt": 0.45, "blush": 0.0, "tone": 0.0, "eye": 0.0, "glasses_amt": 0.0, "wipe": 1.0}


def look_at(events, t, strength):
    """시간표(--timeline)에서 t초의 화장 상태를 구한다. 숫자 값은 fade 초 동안 서서히 바뀐다.
    wipe 는 전/후 분할선의 위치(0~1, 선의 오른쪽이 보정 전). 1 이면 전부 보정 후"""
    L = dict(LOOK, glasses_amt=1.0 if LOOK["glasses"] else 0.0, wipe=1.0, skin=strength)
    if not events:
        return L
    L.update({k: v for k, v in NUM.items() if v is not None}, lip=None, glasses=None)
    L["skin"] = 0.0
    for ev in events:
        if t < ev["at"]:
            break
        p = min(1.0, (t - ev["at"]) / max(1e-3, ev.get("fade", 0.2)))
        for k, v in ev.items():
            if k in ("at", "fade"):
                continue
            if k == "skin":
                v = min(1.0, max(0.0, float(v))) * 0.85
            if k in NUM:
                L[k] = L[k] + (float(v) - L[k]) * p
            else:
                L[k] = v
                if k == "glasses" and "glasses_amt" not in ev:
                    L["glasses_amt"] = p if v else 0.0
    return L


_tags = {}


def wipe_line(frame, orig, L, found, cv2):
    """분할선 오른쪽을 보정 전 화면으로 되돌리고 선과 '전/후' 딱지를 그린다"""
    H, W = frame.shape[:2]
    x = int(round(L["wipe"] * W))
    frame[:, x:] = orig[:, x:]
    t = max(3, W // 220)
    cv2.rectangle(frame, (x - t // 2, 0), (x + t - t // 2, H), (255, 255, 255), -1)
    if not _tags:
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(os.path.join(KIT, "assets", "fonts", "Pretendard-Black.otf"), int(W * 0.05))
        for name, bg, fg in (("전", (22, 22, 26), (255, 255, 255)), ("후", (255, 224, 51), (22, 22, 26))):
            bw, bh = int(W * 0.105), int(W * 0.075)
            im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            dr.rounded_rectangle((0, 0, bw - 1, bh - 1), bh // 3, fill=bg + (255,))
            dr.text((bw / 2, bh / 2), name, font=font, fill=fg + (255,), anchor="mm")
            arr = np.array(im)
            _tags[name] = (arr[..., 2::-1].astype(np.float32), arr[..., 3:].astype(np.float32) / 255)
    y = int(H * 0.12)
    if found:
        f = max(found, key=lambda r: r[0][2])[0]
        y = int(max(H * 0.03, f[1] - 0.75 * f[3]))
    gap = int(W * 0.02)
    for name, left in (("후", True), ("전", False)):
        col, al = _tags[name]
        bh, bw = al.shape[:2]
        xx = x - gap - bw if left else x + gap
        if xx < 0 or xx + bw > W or y + bh > H:
            continue
        roi = frame[y:y + bh, xx:xx + bw]
        roi[:] = (roi * (1 - al) + col * al).astype(np.uint8)


def process(frame, found, L, cv2, show_mask=False):
    """한 프레임에 그 순간의 화장을 입힌다"""
    w = L.get("wipe", 1.0)
    if w <= 0.004:
        return
    orig = frame.copy() if w < 0.996 else None
    for f in found:
        retouch(frame, f, L["skin"], cv2, show_mask, L)
    if orig is not None:
        wipe_line(frame, orig, L, found, cv2)


def decode_cmd(src, hdr, extra=()):
    return ["ffmpeg", "-v", "error", "-nostats", *extra, "-i", src, "-an", "-sn",
            "-vf", TONEMAP if hdr else "format=yuv420p", "-f", "rawvideo", "-pix_fmt", "bgr24"]


def main():
    import cv2
    args = sys.argv[1:]
    opt = {"--strength": "0.6", "--still": None, "--lip": None, "--blush": None, "--tone": None, "--eye": None, "--glasses": None, "--timeline": None, "--eye-color": None}
    show_mask = "--mask" in args
    args = [a for a in args if a != "--mask"]
    for key in list(opt):
        if key in args:
            i = args.index(key)
            opt[key] = args[i + 1]
            del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    src = os.path.abspath(args[0])
    strength = min(1.0, max(0.0, float(opt["--strength"]))) * 0.85     # 1.0 이어도 인형처럼 되지 않게
    if opt["--lip"]:                    # 예: --lip coral  또는  --lip coral:0.8
        name, _, amt = opt["--lip"].partition(":")
        LOOK["lip"], LOOK["lip_amt"] = name, min(1.0, max(0.0, float(amt or 0.45)))
    for key in ("blush", "tone", "eye"):
        if opt["--" + key]:     # 블러셔와 눈 화장은 2까지 (1 넘으면 무대 화장처럼 진하다)
            LOOK[key] = min(1.0 if key == "tone" else 2.0, max(0.0, float(opt["--" + key])))
    if opt["--eye-color"]:
        LOOK["eye_color"] = EYE_COLORS.get(opt["--eye-color"], EYE_COLORS["brown"])
    LOOK["glasses"] = opt["--glasses"]
    events = None
    if opt["--timeline"]:               # 시간에 따라 화장이 바뀌는 시간표 (입력 영상의 초)
        import json
        events = sorted(json.load(open(opt["--timeline"], encoding="utf-8")), key=lambda e: e["at"])
    w, h, fps, hdr, dur = probe(src)
    faces = Faces(w, h)
    stem = os.path.splitext(os.path.basename(src))[0]
    folder = os.path.join(os.path.dirname(src), "피부보정")

    if opt["--still"] is not None:      # 전/후 비교 그림 한 장
        t = float(opt["--still"])
        out = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(folder, f"{stem}_비교_{t:.1f}초.jpg")
        raw = subprocess.run(decode_cmd(src, hdr, ("-ss", f"{t:.3f}")) + ["-frames:v", "1", "-"],
                             capture_output=True).stdout
        if len(raw) != w * h * 3:
            sys.exit("그 시간의 장면을 읽지 못했습니다")
        before = np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()
        after = before.copy()
        found = faces.find(after)
        process(after, found, look_at(events, t, strength), cv2, show_mask)
        if found and not events:                       # 가장 큰 얼굴을 크게 잘라 나란히 놓는다
            x, y, fw, fh = max(found, key=lambda r: r[0][2])[0][:4]
            x0, x1 = int(max(0, x - 0.3 * fw)), int(min(w, x + 1.3 * fw))
            y0, y1 = int(max(0, y - 0.35 * fh)), int(min(h, y + 1.25 * fh))
            before, after = before[y0:y1, x0:x1], after[y0:y1, x0:x1]
        pair = np.hstack([before, np.full((before.shape[0], 6, 3), 255, np.uint8), after])
        if pair.shape[0] > 1100:
            s = 1100 / pair.shape[0]
            pair = cv2.resize(pair, (int(pair.shape[1] * s), 1100), interpolation=cv2.INTER_AREA)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imencode(".jpg", pair, [cv2.IMWRITE_JPEG_QUALITY, 93])[1].tofile(out)
        print(f"얼굴 {len(found)}개. 비교 그림(왼쪽 전, 오른쪽 후): {out}")
        return

    out = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(folder, f"{stem}_피부보정.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rd = subprocess.Popen(decode_cmd(src, hdr) + ["-r", f"{fps:.5f}", "-"], stdout=subprocess.PIPE)
    wr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{w}x{h}", "-r", f"{fps:.5f}", "-i", "-", "-i", src, "-map", "0:v", "-map", "1:a?",
                           "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
                           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                           "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out],
                          stdin=subprocess.PIPE)
    from concurrent.futures import ThreadPoolExecutor
    size, n, hit, total = w * h * 3, 0, 0, max(1, int(dur * fps))
    pool = ThreadPoolExecutor(max(2, min(8, (os.cpu_count() or 4) - 2)))
    print(f"피부 보정 시작: {w}x{h}, {dur:.0f}초", flush=True)

    def fix(job):
        frame, found, t = job
        process(frame, found, look_at(events, t, strength), cv2)

    done = False
    while not done:
        jobs = []
        while len(jobs) < 12:               # 몇 장씩 모아 한꺼번에 보정하고, 순서대로 쓴다
            buf = rd.stdout.read(size)
            if len(buf) < size:
                done = True
                break
            frame = np.frombuffer(bytearray(buf), np.uint8).reshape(h, w, 3)
            found = faces.find(frame)       # 얼굴 찾기는 앞 장면을 참고하므로 순서대로
            hit += bool(found)
            jobs.append((frame, found, (n + len(jobs)) / fps))
        list(pool.map(fix, jobs))
        for frame, _, _ in jobs:
            wr.stdin.write(frame.data)
            n += 1
            if n % max(1, total // 5) == 0 and n < total:
                print(f"  {min(99, round(100 * n / total))}%", flush=True)
    wr.stdin.close()
    wr.wait()
    rd.wait()
    if n == 0 or wr.returncode != 0:
        sys.exit("영상을 만들지 못했습니다")
    print(f"완료: {out}")
    print(f"얼굴이 보인 장면 {round(100 * hit / n)}%" + ("" if hit else " (얼굴을 찾지 못해 바뀐 것이 없습니다)"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
