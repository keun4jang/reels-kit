"""받아쓰기: 영상 -> 단어 단위 타임코드 JSON.  사용: python transcribe.py <영상> <출력.json> [모델] [언어: ko|en|auto]"""
import json, subprocess, sys
import numpy as np


def load_audio(src):
    # PyAV 버전 차이를 피하려고 ffmpeg로 직접 16kHz mono PCM을 읽는다
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def run(model_name, device, compute, audio, lang="ko"):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute)
    segs, info = model.transcribe(audio, language=None if lang == "auto" else lang, word_timestamps=True, vad_filter=True,
                                  condition_on_previous_text=False, beam_size=5)
    return list(segs), info


def main():
    src, out = sys.argv[1], sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) > 3 else "large-v3"
    lang = sys.argv[4] if len(sys.argv) > 4 else "ko"
    audio = load_audio(src)
    try:
        segs, info = run(model_name, "cuda", "float16", audio, lang)
    except Exception as e:
        print("GPU 사용 불가, CPU로 진행:", repr(e)[:200], file=sys.stderr)
        segs, info = run("medium" if model_name == "large-v3" else model_name, "cpu", "int8", audio, lang)
    data = {"duration": round(len(audio) / 16000, 3), "segments": []}
    for s in segs:
        data["segments"].append({
            "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for w in (s.words or [])],
        })
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for s in data["segments"]:
        print(f"[{s['start']:7.2f} - {s['end']:7.2f}] {s['text']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
