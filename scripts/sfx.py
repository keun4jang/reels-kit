"""효과음을 코드로 합성한다(저작권 걱정 없음).  사용: python sfx.py <출력폴더>"""
import os, sys, wave
import numpy as np

SR = 48000
rng = np.random.default_rng(7)


def save(path, x):
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.89
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def t(d):
    return np.arange(int(SR * d)) / SR


def bandnoise(d, f_lo, f_hi):
    """중심 주파수가 f_lo -> f_hi 로 움직이는 대역 잡음"""
    n = int(SR * d)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    lp = bp = 0.0
    fc = np.geomspace(f_lo, f_hi, n)
    q = 0.35
    for i in range(n):  # state-variable filter
        f = 2 * np.sin(np.pi * fc[i] / SR)
        hp = noise[i] - lp - q * bp
        bp += f * hp
        lp += f * bp
        out[i] = bp
    return out


def whoosh():
    d = 0.42
    x = bandnoise(d, 300, 5200)
    tt = t(d)
    env = np.sin(np.pi * tt / d) ** 2.2
    return x * env


def pop():
    d = 0.11
    tt = t(d)
    f = 520 * np.exp(-tt * 14) + 260
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-tt * 38) * np.minimum(1, tt / 0.003)


def ding():
    d = 1.1
    tt = t(d)
    x = sum(a * np.sin(2 * np.pi * f * tt) * np.exp(-tt * k)
            for f, a, k in [(1568, 1.0, 5), (3136, 0.45, 8), (4704, 0.2, 12), (6272, 0.1, 16)])
    return x * np.minimum(1, tt / 0.002)


def impact():
    d = 0.7
    tt = t(d)
    f = 95 * np.exp(-tt * 9) + 42
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 7)
    click = rng.standard_normal(len(tt)) * np.exp(-tt * 90) * 0.5
    return np.tanh((body + click) * 1.8)


def sparkle():
    d = 0.9
    tt = t(d)
    x = np.zeros(len(tt))
    for i, f in enumerate([1760, 2217, 2637, 3520, 4435]):
        s = int(SR * 0.055 * i)
        seg = tt[: len(tt) - s]
        x[s:] += np.sin(2 * np.pi * f * seg) * np.exp(-seg * 9) * np.minimum(1, seg / 0.002) * (0.9 ** i)
    return x


def click():
    d = 0.05
    tt = t(d)
    return (np.sin(2 * np.pi * 2100 * tt) + 0.6 * rng.standard_normal(len(tt))) * np.exp(-tt * 160)


def typing():
    """키보드 치는 소리 (약 0.9초)"""
    out = np.zeros(int(SR * 0.95))
    pos = 0.0
    for i in range(8):
        c = click() * rng.uniform(0.6, 1.0)
        s = int(pos * SR)
        out[s:s + len(c)] += c
        pos += rng.uniform(0.08, 0.13)
    return out


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, fn in [("whoosh", whoosh), ("pop", pop), ("ding", ding), ("impact", impact),
                     ("sparkle", sparkle), ("click", click), ("type", typing)]:
        save(os.path.join(out, name + ".wav"), fn())
        print("만듦:", name)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
