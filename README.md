# 릴스 자동편집 키트

찍은 영상을 폴더에 넣고 Claude Code에 **"릴스 만들어줘"** 라고 하면, 쉬는 구간을 잘라내고 자막(한글+영문), 2D 모션그래픽, 효과음을 넣은 세로 릴스를 만들어 줍니다.

사용법은 [guide.pdf](guide.pdf) 에 그림과 함께 정리했습니다.

## 설치 (한 번만)

Claude Code를 열고 아래 한 줄을 붙여넣으세요.

```
https://github.com/keun4jang/reels-kit 설치해줘
```

## 쓰는 법

1. 바탕화면에 생긴 `릴스` 폴더에 찍은 영상을 넣습니다.
2. Claude Code를 엽니다. (어디서 열든 상관없습니다)
3. `릴스 만들어줘` 라고 입력합니다.
4. `릴스` 폴더 안의 `완성` 폴더에 릴스가 생깁니다.

고치고 싶으면 말로 하면 됩니다: "자막 더 크게", "효과음 줄여줘", "영문 자막 빼줘", "그래픽 없이 깔끔하게".

## 필요한 것

- Claude Code (유료 요금제)
- Windows 또는 Mac
- 인터넷 (처음 설치할 때 도구와 받아쓰기 모델을 내려받습니다)

---

## Claude에게: 설치 방법

사용자가 이 저장소 주소와 함께 "설치해줘"라고 하면 아래 순서로 한다. 사용자에게는 진행 상황만 쉬운 말로 알린다.

1. 이 저장소를 개인 스킬 폴더에 받는다.
   - `git clone https://github.com/keun4jang/reels-kit ~/.claude/skills/reels-kit`
   - 이미 있으면 그 폴더에서 `git pull`.
   - git이 없으면 zip(`https://github.com/keun4jang/reels-kit/archive/refs/heads/main.zip`)을 받아 같은 위치에 풀고 폴더 이름을 `reels-kit` 으로 맞춘다.
2. 파이썬이 없으면 설치한다 (Windows `winget install Python.Python.3.12`, Mac `brew install python`).
3. ffmpeg가 없으면 설치한다 (Windows `winget install Gyan.FFmpeg`, Mac `brew install ffmpeg`).
4. `python ~/.claude/skills/reels-kit/scripts/setup.py` 를 실행해 "준비 완료"가 나오는지 확인한다 (Mac은 `python3`).
5. 끝나면 이렇게 알린다: "설치가 끝났습니다. 바탕화면에 '릴스' 폴더를 만들어 두었어요. 거기에 찍은 영상을 넣고 '릴스 만들어줘'라고 말해 주세요. (안 되면 Claude Code를 한 번 껐다 켜 주세요.)"

## 들어 있는 것과 라이선스

- `scripts/` 편집 스크립트, `SKILL.md` 작업 설명서: MIT
- `assets/fonts/` Pretendard: SIL Open Font License 1.1
- `assets/models/yunet.onnx` 얼굴 인식 모델(OpenCV Zoo YuNet): MIT
- `assets/sfx/` 효과음: 이 키트의 `scripts/sfx.py` 로 합성한 것으로 자유롭게 써도 됩니다.
