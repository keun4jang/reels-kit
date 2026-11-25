"""2단계 렌더: 모션그래픽 패널 + 자막(한글/영문) + 효과음을 base.mp4 위에 얹는다.
사용: python gfx.py <edit.json> <base.mp4> <완성.mp4>
미리보기: python gfx.py <edit.json> <base.mp4> --still 1.0,5.5,12 <출력폴더>"""
import math, os, random, subprocess, sys
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import timeline as TL

W, H, FPS = TL.W, TL.H, TL.FPS
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = {k: os.path.join(KIT, "assets", "fonts", f"Pretendard-{v}.otf")
        for k, v in (("black", "Black"), ("bold", "Bold"), ("semi", "SemiBold"))}
SS = 3
INK, YEL, RED, GRN, BLUE, ORG, GRAY = "#16161A", "#FFE033", "#F0443A", "#22C55E", "#3B82F6", "#FF8A3D", "#A1A1AA"
PX, PY = 540, 452          # 패널 그래픽의 중심
CAP_Y, EN_Y = 858, 942     # 한글/영문 자막 높이
_cache = {}


# ---------- 기본 도구 ----------
def c01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease(x):
    return 1 - (1 - c01(x)) ** 3


def back(x):
    x = c01(x)
    return 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2


def prog(t, at, dur):
    return c01((t - at) / dur)


def pop(t, at, dur=0.3):
    return 0.0 if t < at else back((t - at) / dur)


@lru_cache(None)
def font(kind, size):
    return ImageFont.truetype(FONT[kind], size)


@lru_cache(None)
def text(txt, kind="black", size=48, fill=INK, stroke=0, stroke_fill="#000000", maxw=0):
    """*별표* 로 감싼 부분은 노란색. 고정 줄 높이의 글자 그림을 돌려준다."""
    segs, hi = [], False
    for part in txt.split("*"):
        if part:
            segs.append((part, YEL if hi else fill))
        hi = not hi
    f = font(kind, size)
    asc, desc = f.getmetrics()
    pad = stroke + 8
    widths = [f.getlength(s) for s, _ in segs]
    img = Image.new("RGBA", (int(sum(widths)) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if stroke:
        x = pad
        for (s, _), w in zip(segs, widths):
            d.text((x, pad + max(3, stroke // 2)), s, font=f, fill=stroke_fill, stroke_width=stroke, stroke_fill=stroke_fill)
            d.text((x, pad), s, font=f, fill=stroke_fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += w
    x = pad
    for (s, col), w in zip(segs, widths):
        d.text((x, pad), s, font=f, fill=col)
        x += w
    if maxw and img.width > maxw:
        img = img.resize((maxw, int(img.height * maxw / img.width)), Image.LANCZOS)
    return img


def shape(key, w, h, fn):
    """fn(draw, s) 로 그린 도형을 3배 크기로 그렸다 줄여 가장자리를 매끈하게 만든다."""
    if key not in _cache:
        img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        fn(ImageDraw.Draw(img), SS)
        _cache[key] = img.resize((w, h), Image.LANCZOS)
    return _cache[key]


def rrect(w, h, r, fill, outline=None, ow=0):
    return shape(("rr", w, h, r, fill, outline, ow), w, h,
                 lambda d, s: d.rounded_rectangle((ow * s // 2, ow * s // 2, w * s - 1 - ow * s // 2, h * s - 1 - ow * s // 2),
                                                  r * s, fill=fill, outline=outline, width=ow * s))


def shadowed(key, spr, blur=26, dy=14, alpha=70):
    k = ("sh", key)
    if k not in _cache:
        m = blur * 3
        out = Image.new("RGBA", (spr.width + m * 2, spr.height + m * 2), (0, 0, 0, 0))
        sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, alpha), (m, m + dy), spr.getchannel("A"))
        out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(blur)))
        out.alpha_composite(spr, (m, m))
        _cache[k] = out
    return _cache[k]


def put(cv, spr, cx, cy, scale=1.0, alpha=1.0, anchor="c", rot=0.0):
    if scale <= 0.02 or alpha <= 0.02:
        return
    if abs(scale - 1) > 1e-3:
        spr = spr.resize((max(1, round(spr.width * scale)), max(1, round(spr.height * scale))), Image.BILINEAR)
    if rot:
        spr = spr.rotate(rot, expand=True, resample=Image.BICUBIC)
    if alpha < 0.995:
        spr = spr.copy()
        spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    x = round(cx - spr.width / 2) if anchor in "c" else round(cx)
    y = round(cy - spr.height / 2) if anchor in ("c", "lc") else round(cy)
    if anchor == "lc":
        x = round(cx)
    if anchor == "rc":
        x = round(cx - spr.width)
        y = round(cy - spr.height / 2)
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(spr.width, W - x), min(spr.height, H - y)
    if ex > sx and ey > sy:
        cv.alpha_composite(spr, (x + sx, y + sy), (sx, sy, ex, ey))


def label(cv, txt, x, y, kind="bold", size=40, fill=INK, anchor="lc", alpha=1.0, scale=1.0, **kw):
    put(cv, text(txt, kind, size, fill, **kw), x, y, scale, alpha, anchor)


# ---------- 자주 쓰는 그림 ----------
def check_icon(size=64, color=GRN):
    def fn(d, s):
        d.ellipse((0, 0, size * s - 1, size * s - 1), fill=color)
        p = [(0.27, 0.53), (0.44, 0.69), (0.74, 0.35)]
        d.line([(x * size * s, y * size * s) for x, y in p], fill="#FFFFFF", width=int(size * s * 0.11), joint="curve")
    return shape(("chk", size, color), size, size, fn)


def x_icon(size=260):
    def fn(d, s):
        n = size * s
        d.ellipse((0, 0, n - 1, n - 1), fill=RED)
        a, b, wd = n * 0.30, n * 0.70, int(n * 0.13)
        d.line((a, a, b, b), fill="#FFFFFF", width=wd)
        d.line((a, b, b, a), fill="#FFFFFF", width=wd)
        for px, py in ((a, a), (b, b), (a, b), (b, a)):
            d.ellipse((px - wd / 2, py - wd / 2, px + wd / 2, py + wd / 2), fill="#FFFFFF")
    return shadowed(("x", size), shape(("x", size), size, size, fn), 20, 10, 90)


def window(w, h, title, dark=False):
    key = ("win", w, h, title, dark)
    if key not in _cache:
        bg, bar, tc = ("#1B1B20", "#26262D", "#8E8E99") if dark else ("#FFFFFF", "#F4F4F5", "#8E8E99")
        img = rrect(w, h, 34, bg).copy()
        top = rrect(w, 76, 34, bar).copy()
        ImageDraw.Draw(top).rectangle((0, 40, w, 76), fill=bar)
        img.alpha_composite(top, (0, 0))
        dots = shape(("dots",), 120, 30, lambda d, s: [d.ellipse(((6 + i * 38) * s, 3 * s, (30 + i * 38) * s, 27 * s), fill=c)
                                                       for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840"))])
        img.alpha_composite(dots, (28, 23))
        t = text(title, "semi", 28, tc)
        img.alpha_composite(t, (160, 38 - t.height // 2))
        img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), rrect(w, h, 34, "#FFFFFF").getchannel("A")))
        _cache[key] = shadowed(key, img)
    return _cache[key]


def header(cv, brand, tag, dark=False):
    col = "#FFFFFF" if dark else INK
    label(cv, brand, 52, 70, "black", 36, col)
    if tag:
        t = text(tag, "bold", 28, col)
        w = t.width + 36
        put(cv, rrect(w, 54, 27, None, col, 3), W - 52, 70, anchor="rc")
        put(cv, t, W - 52 - w / 2, 70)


def enter(t, sc, dur=0.3):
    """장면이 시작할 때 살짝 커지며 나타나는 정도 (크기, 투명도)"""
    p = ease((t - sc["o0"]) / dur)
    return 0.92 + 0.08 * p, p


# ---------- 장면들 ----------
def sc_timeline(cv, t, sc):
    s, a = enter(t, sc)
    win = window(960, 620, "편집 프로그램  ·  타임라인")
    put(cv, win, PX, PY, s, a)
    if a < 1:
        return
    left, top = PX - 430, PY - 190
    rnd = random.Random(3)
    tracks = [("V2", "#A78BFA"), ("V1", BLUE), ("A1", GRN), ("A2", "#F59E0B")]
    for r, (name, col) in enumerate(tracks):
        y = top + r * 104
        put(cv, rrect(860, 84, 14, "#F4F4F5"), left, y, anchor="lt")
        label(cv, name, left + 18, y + 42, "bold", 26, GRAY)
        x = left + 84
        while x < left + 830:
            wd = rnd.randint(70, 190)
            wd = min(wd, left + 846 - x)
            if wd > 30 and rnd.random() > 0.18:
                put(cv, rrect(wd, 60, 12, col), x, y + 12, anchor="lt")
            x += wd + 10
    ph = left + 84 + 760 * c01((t - sc["o0"]) / (sc["o1"] - sc["o0"]))
    ImageDraw.Draw(cv).rectangle((ph - 3, top - 26, ph + 3, top + 404), fill=RED)
    put(cv, shape(("phd",), 34, 30, lambda d, q: d.polygon([(0, 0), (34 * q, 0), (17 * q, 30 * q)], fill=RED)), ph, top - 26)
    k = pop(t, sc["c"].get("x", 1e9), 0.32)
    if k > 0:
        put(cv, rrect(900, 470, 20, "#FFFFFF"), PX, PY + 36, alpha=0.72 * c01(k))
        put(cv, x_icon(300), PX, PY + 30, k, rot=-8)


def sc_checklist(cv, t, sc):
    s, a = enter(t, sc)
    put(cv, window(960, 620, sc.get("window", "할 일")), PX, PY, s, a)
    if a < 1:
        return
    left, top = PX - 420, PY - 200
    label(cv, sc["title"], left, top + 20, "black", 56)
    for i, it in enumerate(sc["items"]):
        y = top + 128 + i * 124
        at = sc["c"][f"i{i}"]
        on = t >= at
        k = pop(t, at, 0.26)
        put(cv, rrect(840, 100, 22, "#F4F4F5" if not on else "#ECFDF3"), left, y - 50, anchor="lt")
        put(cv, shape(("ring",), 60, 60, lambda d, q: d.ellipse((3 * q, 3 * q, 57 * q, 57 * q), outline="#D4D4D8", width=5 * q)), left + 60, y)
        if on:
            put(cv, check_icon(60), left + 60, y, k)
        label(cv, it, left + 116, y, "black", 50, INK if on else "#B4B4BB")
    at = sc["c"].get("time", 1e9) if sc.get("badge") else 1e9
    if t >= at:
        p = ease((t - at) / 0.22)
        b = text(sc["badge"], "black", 104, "#FFFFFF")
        card = shadowed(("badge", sc["badge"]), rrect(b.width + 90, 190, 44, RED), 22, 12, 110)
        put(cv, card, PX + 190, PY + 110, 2.2 - 1.2 * p, p, rot=-7)
        put(cv, b, PX + 190, PY + 110, 2.2 - 1.2 * p, p, rot=-7)


def sc_dark(cv, t, sc):
    cv.paste((14, 14, 17, 255), (0, 0, W, H))
    sprs = [text(l["text"], "black", l["size"], l["color"], maxw=980) for l in sc["lines"]]
    gap = 26
    total = sum(s.height for s in sprs) + gap * (len(sprs) - 1)
    y = 800 - total / 2
    for l, s in zip(sc["lines"], sprs):
        at = l["o"]
        if t >= at:
            p = ease((t - at) / 0.2)
            put(cv, s, W / 2, y + s.height / 2, 1.5 - 0.5 * p if l["size"] >= 120 else 0.8 + 0.2 * back((t - at) / 0.25), p)
        y += s.height + gap


def chip(cv, step, txt, alpha=1.0):
    st = text(step, "black", 30, YEL)
    w = st.width + 30
    put(cv, rrect(w, 56, 28, INK), 70, 176, alpha=alpha, anchor="lc")
    put(cv, st, 70 + w / 2, 176, alpha=alpha)
    label(cv, txt, 70 + w + 20, 176, "black", 46, alpha=alpha)


def folder_icon():
    def fn(d, s):
        d.rounded_rectangle((0, 0, 190 * s, 110 * s), 26 * s, fill="#F2B21F")
        d.rounded_rectangle((0, 50 * s, 440 * s - 1, 330 * s - 1), 34 * s, fill="#FFC83D")
        d.rounded_rectangle((0, 50 * s, 440 * s - 1, 96 * s), 34 * s, fill="#FFD76A")
    return shadowed(("folder",), shape(("folder",), 440, 330, fn))


def file_icon(name):
    key = ("file", name)
    if key not in _cache:
        img = rrect(260, 200, 26, "#22222A").copy()
        tri = shape(("tri",), 70, 80, lambda d, s: d.polygon([(4 * s, 2 * s), (68 * s, 40 * s), (4 * s, 78 * s)], fill="#FFFFFF"))
        img.alpha_composite(tri, (100, 36))
        nm = text(name, "semi", 26, "#D4D4D8")
        img.alpha_composite(nm, (130 - nm.width // 2, 136))
        _cache[key] = shadowed(key, img, 18, 10, 80)
    return _cache[key]


def sc_howto(cv, t, sc):
    c = sc["c"]
    if t < c["type"]:                       # 1) 폴더에 넣기
        s, a = enter(t, sc)
        chip(cv, "STEP 1", "영상을 폴더에 넣기", a)
        land = c.get("drop", sc["o0"] + 0.85)
        bounce = 1 + 0.07 * math.sin(c01((t - land) / 0.35) * math.pi) if t >= land else 1
        put(cv, folder_icon(), PX, PY + 110, s * bounce, a)
        p = ease((t - (land - 0.5)) / 0.5)
        if t >= land - 0.5:
            gone = prog(t, land, 0.22)
            put(cv, file_icon(sc["file"]), PX, PY - 260 + 330 * p, 1 - 0.45 * gone, 1 - gone, rot=-6 * (1 - p))
        return
    done = t >= c["done"]
    s, a = (1, 1)
    p0 = ease((t - c["type"]) / 0.25)
    chip(cv, "끝!" if done else "STEP 2", "이게 전부예요" if done else "한마디 입력")
    put(cv, window(940, 430, "Claude Code", dark=True), PX, PY + 60, 0.92 + 0.08 * p0, p0)
    if p0 < 1:
        return
    left, y = PX - 410, PY - 30
    label(cv, "›", left, y, "black", 72, ORG)
    cmd = sc["command"]
    n = len(cmd) if done else int(len(cmd) * c01((t - c["type"] - 0.2) / 0.75) + 0.001)
    tx = text(cmd[:n], "black", 76, "#FFFFFF") if n else None
    if tx:
        put(cv, tx, left + 54, y, anchor="lc")
    if not done and int(t * 3.2) % 2 == 0:
        x = left + 54 + (tx.width - 12 if tx else 6)
        ImageDraw.Draw(cv).rectangle((x, y - 40, x + 10, y + 40), fill=ORG)
    if done:
        for i, w_ in enumerate(("컷편집", "자막", "효과음")):
            k = pop(t, c["done"] + 0.1 + i * 0.13, 0.25)
            if k > 0:
                x = left + 30 + i * 250
                put(cv, check_icon(44), x, y + 130, k)
                label(cv, w_, x + 36, y + 130, "bold", 40, "#E4E4E7", alpha=c01(k))
        put(cv, shadowed(("bigchk",), check_icon(190), 18, 10, 90), PX + 340, PY - 110, pop(t, c["done"], 0.34), rot=-8)


def sc_cutter(cv, t, sc):
    s, a = enter(t, sc)
    put(cv, window(960, 600, sc["title"]), PX, PY, s, a)
    if a < 1:
        return
    cut = sc["c"]["cut"]
    k = ease((t - cut) / 0.45)
    segs = [("s", 150), ("g", 90), ("s", 210), ("g", 70), ("s", 130), ("g", 110), ("s", 120)]
    widths = [w if kind == "s" else w * (1 - k) for kind, w in segs]
    total = sum(widths) + 0
    x = PX - total / 2
    y = PY - 20
    rnd = random.Random(11)
    d = ImageDraw.Draw(cv)
    blink = 0.55 + 0.45 * math.sin(t * 9) if t < cut else 1
    for (kind, w0), w in zip(segs, widths):
        if kind == "s":
            def fn(dr, q, w0=w0, seed=rnd.randint(0, 999)):
                dr.rounded_rectangle((0, 0, w0 * q - 1, 170 * q - 1), 18 * q, fill=BLUE)
                r2 = random.Random(seed)
                for bx in range(14, w0 - 10, 12):
                    hh = r2.randint(16, 62)
                    dr.rounded_rectangle((bx * q, (85 - hh) * q, (bx + 6) * q, (85 + hh) * q), 3 * q, fill="#DCEBFF")
            put(cv, shape(("sp", w0), w0 - 6, 170, fn), x + w / 2, y)
        elif w > 6:
            col = (253, 214, 211, 255) if blink < 0.75 else (251, 178, 172, 255)
            d.rectangle((x + 2, y - 85, x + w - 2, y + 85), fill=col)
            if w > 54:
                label(cv, "쉼", x + w / 2, y, "bold", 30, RED, anchor="c")
        x += w
    label(cv, "말한 구간", PX - 420, PY - 150, "bold", 30, BLUE)
    label(cv, "쉬는 구간", PX - 250, PY - 150, "bold", 30, RED)
    by = PY + 170
    if t < cut:
        label(cv, sc["before"], PX, by, "black", 60, GRAY, anchor="c")
    else:
        b1 = text(sc["before"] + "  →", "black", 54, GRAY)
        b2 = text(sc["after"], "black", 76, GRN)
        x0 = PX - (b1.width + b2.width + 10) / 2
        put(cv, b1, x0, by, anchor="lc")
        put(cv, b2, x0 + b1.width + 10 + b2.width / 2, by, pop(t, cut + 0.25, 0.3))


def feat_icon(i):
    def cap(d, s):
        d.rounded_rectangle((0, 14 * s, 150 * s, 126 * s), 22 * s, fill=INK)
        d.rounded_rectangle((24 * s, 52 * s, 80 * s, 68 * s), 8 * s, fill=YEL)
        d.rounded_rectangle((90 * s, 52 * s, 126 * s, 68 * s), 8 * s, fill="#FFFFFF")
        d.rounded_rectangle((24 * s, 84 * s, 112 * s, 100 * s), 8 * s, fill="#FFFFFF")

    def snd(d, s):
        d.polygon([(10 * s, 52 * s), (44 * s, 52 * s), (84 * s, 18 * s), (84 * s, 122 * s), (44 * s, 88 * s), (10 * s, 88 * s)], fill=INK)
        for r in (30, 54):
            d.arc(((84 - r) * s, (70 - r) * s, (84 + r) * s, (70 + r) * s), -42, 42, fill=ORG, width=11 * s)

    def zoom(d, s):
        d.line((92 * s, 92 * s, 136 * s, 136 * s), fill=INK, width=18 * s)
        d.ellipse((10 * s, 10 * s, 110 * s, 110 * s), outline=INK, width=13 * s, fill="#E8F1FF")
        d.line((40 * s, 60 * s, 80 * s, 60 * s), fill=BLUE, width=11 * s)
        d.line((60 * s, 40 * s, 60 * s, 80 * s), fill=BLUE, width=11 * s)
    def num(d, s):
        d.ellipse((15 * s, 10 * s, 135 * s, 130 * s), fill=INK)
    if isinstance(i, int):
        return shape(("feat", i), 150, 140, (cap, snd, zoom)[i])
    key = ("featn", i)
    if key not in _cache:
        img = shape(("featbg",), 150, 140, num).copy()
        tx = text(str(i), "black", 72, YEL)
        img.alpha_composite(tx, (75 - tx.width // 2, 70 - tx.height // 2))
        _cache[key] = img
    return _cache[key]


ICONS = {"caption": 0, "자막": 0, "sound": 1, "효과음": 1, "zoom": 2, "줌인": 2}


def sc_features(cv, t, sc):
    s, a = enter(t, sc)
    label(cv, sc.get("title", ""), PX, 190, "black", 54, anchor="c", alpha=a)
    card = shadowed(("fcard",), rrect(300, 440, 40, "#FFFFFF"))
    cy = PY + 60
    for i, it in enumerate(sc["items"]):
        x = PX + (i - 1) * 326
        k = pop(t, sc["c"][f"i{i}"], 0.3)
        if k <= 0:
            put(cv, rrect(300, 440, 40, None, "#DAD6CE", 4), x, cy)
            continue
        put(cv, card, x, cy, k)
        put(cv, feat_icon(ICONS.get(sc.get("icons", [None] * 9)[i] or it, str(i + 1))), x, cy - 60, k * 1.35)
        label(cv, it, x, cy + 120, "black", 62, anchor="c", scale=c01(k))
        put(cv, check_icon(72), x + 120, cy - 190, pop(t, sc["c"][f"i{i}"] + 0.12, 0.25))


def sc_rawintro(cv, t, sc):
    s, a = enter(t, sc, 0.22)
    key = ("rawcard",)
    if key not in _cache:
        img = rrect(560, 440, 34, "#22222A").copy()
        d = ImageDraw.Draw(img)
        for i in range(6):
            d.rounded_rectangle((26, 30 + i * 68, 58, 70 + i * 68), 6, fill="#3A3A44")
            d.rounded_rectangle((502, 30 + i * 68, 534, 70 + i * 68), 6, fill="#3A3A44")
        tri = shape(("tri2",), 110, 126, lambda dr, q: dr.polygon([(6 * q, 3 * q), (106 * q, 63 * q), (6 * q, 123 * q)], fill="#FFFFFF"))
        img.alpha_composite(tri, (232, 157))
        _cache[key] = shadowed(key, img)
    put(cv, _cache[key], PX, PY + 30, s, a, rot=-3)
    label(cv, "편집 전 원본", PX, 186, "black", 58, anchor="c", alpha=a)


def sc_raw(cv, t, sc):
    tx = text(sc["label"], "black", 44, "#FFFFFF")
    w = tx.width + 110
    put(cv, rrect(w, 84, 42, "#000000"), 56, 170, alpha=0.72, anchor="lc")
    if int(t * 2.5) % 2 == 0:
        put(cv, shape(("rec",), 30, 30, lambda d, s: d.ellipse((0, 0, 30 * s - 1, 30 * s - 1), fill=RED)), 100, 170)
    put(cv, tx, 130, 170, anchor="lc")
    label(cv, sc["note"], W / 2, 1480, "black", 52, "#FFFFFF", anchor="c", stroke=8)


def sc_pdf(cv, t, sc):
    p = ease((t - sc["o0"]) / 0.35)
    key = ("paper",)
    if key not in _cache:
        _cache[key] = shadowed(key, rrect(880, 620, 30, "#FFFFFF"))
    oy = (1 - p) * 160
    put(cv, _cache[key], PX, PY + oy, 1, p)
    if p < 1:
        return
    left, top = PX - 380, PY - 250
    label(cv, sc["title"], left, top + 26, "black", 54)
    ImageDraw.Draw(cv).rectangle((left, top + 76, left + 760, top + 80), fill="#E4E4E7")
    for i, st in enumerate(sc["steps"]):
        at = sc["c"][f"s{i}"]
        k = ease((t - at) / 0.25)
        if t < at:
            continue
        y = top + 160 + i * 124
        num = shape(("num", i), 76, 76, lambda d, s: d.ellipse((0, 0, 76 * s - 1, 76 * s - 1), fill=INK))
        put(cv, num, left + 38 - 30 * (1 - k), y, alpha=k)
        label(cv, str(i + 1), left + 38 - 30 * (1 - k), y, "black", 44, YEL, anchor="c", alpha=k)
        label(cv, st, left + 104 - 30 * (1 - k), y, "black", 50, alpha=k)
    at = sc["c"].get("stamp", 1e9)
    if t >= at:
        q = ease((t - at) / 0.2)
        tg = text(sc.get("stamp", "PDF"), "black", 76, "#FFFFFF")
        put(cv, shadowed(("pdftag", tg.width), rrect(tg.width + 70, 130, 30, RED), 18, 10, 100), PX + 330, PY - 250, 2 - q, q, rot=9)
        put(cv, tg, PX + 330, PY - 250, 2 - q, q, rot=9)


def sc_dm(cv, t, sc):
    s, a = enter(t, sc)
    c = sc["c"]
    # 1) 프로필 + 팔로우 버튼
    row = shadowed(("row",), rrect(940, 150, 40, "#FFFFFF"), 20, 10, 50)
    put(cv, row, PX, 220, s, a)
    if a < 1:
        return
    put(cv, shape(("ava",), 96, 96, lambda d, q: (d.ellipse((0, 0, 96 * q - 1, 96 * q - 1), fill=ORG),
                                                    d.ellipse((30 * q, 20 * q, 66 * q, 56 * q), fill="#FFFFFF"),
                                                    d.pieslice((14 * q, 58 * q, 82 * q, 130 * q), 180, 360, fill="#FFFFFF"))), 140, 220)
    label(cv, sc.get("name", "내 계정"), 210, 220, "black", 46)
    on = t >= c["follow"]
    k = 1 + 0.12 * math.sin(c01((t - c["follow"]) / 0.3) * math.pi) if on else 1
    put(cv, rrect(250, 88, 28, "#E9E9EE" if on else BLUE), 850, 220, k)
    label(cv, "팔로잉" if on else "팔로우", 850 + (22 if on else 0), 220, "black", 40, INK if on else "#FFFFFF", anchor="c", scale=k)
    if on:
        put(cv, check_icon(40), 772, 220, pop(t, c["follow"], 0.25))
    # 2) 댓글
    k = pop(t, c["comment"], 0.3)
    if k > 0:
        cm = text(sc["comment"], "black", 70, INK)
        bw = cm.width + 250
        bub = shadowed(("cbub", bw), rrect(bw, 170, 44, "#FFFFFF"), 20, 10, 50)
        cx = 70 + bw / 2
        put(cv, bub, cx, 430, k)
        if k > 0.95:
            put(cv, shape(("ava2",), 84, 84, lambda d, q: d.ellipse((0, 0, 84 * q - 1, 84 * q - 1), fill="#C9C5BD")), 140, 430)
            label(cv, "댓글", 200, 392, "bold", 28, GRAY)
            put(cv, cm, 200, 446, anchor="lc")
    # 3) 자동 DM
    at = c["dm"]
    if t >= at:
        q = ease((t - at) / 0.3)
        bw = 640
        bub = shadowed(("dbub",), rrect(bw, 230, 48, "#6D5DF6"), 22, 12, 80)
        cx = W - 70 - bw / 2 + (1 - q) * 240
        put(cv, bub, cx, 665, 1, q)
        label(cv, "자동 DM 도착", cx - bw / 2 + 44, 600, "bold", 34, "#E3DFFF", alpha=q)
        put(cv, rrect(bw - 88, 100, 26, "#FFFFFF"), cx, 700, alpha=q)
        put(cv, rrect(92, 60, 14, RED), cx - bw / 2 + 110, 700, alpha=q)
        label(cv, "PDF", cx - bw / 2 + 110, 700, "black", 30, "#FFFFFF", anchor="c", alpha=q)
        label(cv, sc["file"], cx - bw / 2 + 176, 700, "black", 42, alpha=q)


def sc_keyword(cv, t, sc):
    """큰 글자 한 줄(+작은 설명). 딱 맞는 그림이 없을 때 쓰는 기본 장면"""
    k = pop(t, sc["o0"], 0.32)
    tx = text(sc["text"], "black", sc.get("size", 150), sc.get("color", INK), maxw=960)
    bar = rrect(min(980, tx.width + 40), 46, 16, YEL)
    put(cv, bar, PX, PY + tx.height * 0.22, alpha=c01(k))
    put(cv, tx, PX, PY - 20, 0.7 + 0.3 * k, c01(k))
    if sc.get("sub"):
        label(cv, sc["sub"], PX, PY + 150, "bold", 52, "#6B6B76", anchor="c", alpha=ease((t - sc["o0"] - 0.2) / 0.3), maxw=940)


def sc_stat(cv, t, sc):
    """숫자가 올라가는 장면: value(숫자), unit(단위), label(설명)"""
    p = ease((t - sc["o0"]) / 0.7)
    v = sc["value"] * p
    num = f"{v:,.0f}" if float(sc["value"]).is_integer() else f"{v:,.1f}"
    n = text(num, "black", 250, sc.get("color", INK))
    u = text(sc.get("unit", ""), "black", 110, sc.get("color", INK)) if sc.get("unit") else None
    wd = n.width + (u.width if u else 0)
    put(cv, n, PX - wd / 2, PY, anchor="lc")
    if u:
        put(cv, u, PX - wd / 2 + n.width, PY + 46, anchor="lc")
    if sc.get("label"):
        label(cv, sc["label"], PX, PY - 200, "bold", 56, "#6B6B76", anchor="c", maxw=940)


SCENES = {"keyword": sc_keyword, "stat": sc_stat, "timeline": sc_timeline, "checklist": sc_checklist, "dark": sc_dark, "howto": sc_howto,
          "cutter": sc_cutter, "features": sc_features, "rawintro": sc_rawintro, "raw": sc_raw,
          "pdf": sc_pdf, "list": sc_pdf, "cards": sc_features, "dm": sc_dm}


# ---------- 한 장면 그리기 ----------
def prepare(plan):
    for sc in plan.get("scenes", []):
        sc["o0"], sc["o1"] = TL.to_out(plan, sc["from"]), TL.to_out(plan, sc["to"])
        sc["c"] = {k: TL.to_out(plan, v) for k, v in sc.get("cues", {}).items()}
        span = sc["o1"] - sc["o0"]
        for pre, key in (("i", "items"), ("s", "steps")):       # 큐를 안 적으면 고르게 나눠 등장
            n = len(sc.get(key, []))
            for i in range(n):
                sc["c"].setdefault(f"{pre}{i}", sc["o0"] + span * (i + 1) / (n + 2))
        defaults = {"howto": {"type": 0.4, "done": 0.75}, "cutter": {"cut": 0.6},
                    "dm": {"follow": 0.15, "comment": 0.4, "dm": 0.7}}.get(sc["type"], {})
        for k, frac in defaults.items():
            sc["c"].setdefault(k, sc["o0"] + span * frac)
        for l in sc.get("lines", []):
            l["o"] = TL.to_out(plan, l["at"])
    caps = []
    for c in plan["clips"]:
        cs = c.get("captions", [])
        for i, cp in enumerate(cs):
            s = c["out"] + max(0, cp["s"] - c["start"])
            e = c["out"] + (cs[i + 1]["s"] - c["start"] if i + 1 < len(cs) else c["dur"])
            caps.append((s, min(e, c["out"] + c["dur"]), cp["text"]))
    plan["caps"] = caps
    plan["ens"] = [(c["out"], c["out"] + c["dur"], c.get("en", "")) for c in plan["clips"]]


def draw(plan, t):
    cv = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    full = plan.get("layout", "split") == "full"
    sc = None
    for s in plan.get("scenes", []):
        if s["o0"] - 1e-4 <= t and not (full and s["type"] not in ("dark", "raw")):
            sc = s if t < s["o1"] or not full else None
    kind = sc["type"] if sc else None
    if sc:
        SCENES[kind](cv, t, sc)
    if kind not in ("raw",) and not (full and kind != "dark"):
        header(cv, plan.get("brand", ""), sc.get("tag") if sc else None, dark=(kind == "dark"))
    en = next((x for a, b, x in plan["ens"] if a - 1e-4 <= t < b), "")
    if kind == "dark":
        if en:
            put(cv, text(en, "bold", 42, "#C8C8D0", maxw=980), W / 2, 1220)
        return cv
    if kind == "raw":
        return cv
    for a, b, tx in plan["caps"]:
        if a - 1e-4 <= t < b:
            k = back((t - a) / 0.16)
            put(cv, text(tx, "black", 92 if full else 80, "#FFFFFF", stroke=10 if full else 9, maxw=1010),
                W / 2, 1290 if full else CAP_Y, 0.82 + 0.18 * k)
            break
    if en:
        put(cv, text(en, "bold", 44 if full else 38, "#FFFFFF", stroke=6, maxw=1010), W / 2, 1390 if full else EN_Y)
    return cv


def main():
    plan_path, base = sys.argv[1], sys.argv[2]
    plan = TL.load(plan_path)
    prepare(plan)
    if sys.argv[3] == "--still":
        outdir = sys.argv[5]
        os.makedirs(outdir, exist_ok=True)
        for ts in sys.argv[4].split(","):
            t = float(ts)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", base, "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
            bg = Image.frombytes("RGBA", (W, H), raw) if len(raw) == W * H * 4 else Image.new("RGBA", (W, H), "#F2EFE9")
            bg.alpha_composite(draw(plan, t))
            bg.convert("RGB").resize((540, 960), Image.LANCZOS).save(os.path.join(outdir, f"still_{t:06.2f}.jpg"), quality=88)
        return
    out = sys.argv[3]
    sfx_dir = os.path.join(KIT, "assets", "sfx")
    events = [(TL.to_out(plan, e["at"]), e["name"], e.get("vol", 0.8) * plan.get("sfx_volume", 0.5)) for e in plan.get("sfx", [])]
    args = ["ffmpeg", "-y", "-v", "error", "-stats", "-i", base, "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    fc = ["[0:v][1:v]overlay=format=auto:shortest=1,format=yuv420p[v]"]
    for i, (at, name, vol) in enumerate(events):
        args += ["-i", os.path.join(sfx_dir, name + ".wav")]
        fc.append(f"[{i + 2}:a]aresample=48000,volume={vol:.3f},adelay={int(at * 1000)}:all=1[s{i}]")
    mix = "[0:a]" + "".join(f"[s{i}]" for i in range(len(events)))
    fc.append(f"{mix}amix=inputs={len(events) + 1}:normalize=0:duration=first,alimiter=limit=0.95[a]")
    args += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
             "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    p = subprocess.Popen(args, stdin=subprocess.PIPE)
    n = round(plan["total"] * FPS)
    for i in range(n):
        p.stdin.write(draw(plan, i / FPS).tobytes())
    p.stdin.close()
    p.wait()
    print(f"완성: {out} ({plan['total']:.1f}초)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
