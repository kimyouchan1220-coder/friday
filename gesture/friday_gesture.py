"""프라이데이 손짓 제어 (Windows)

웹캠으로 손을 인식해서, 손바닥을 편 채 오른쪽/왼쪽으로 치우면 키보드 단축키를 대신 누릅니다.
영상은 이 컴퓨터 안에서만 처리하며 저장하거나 전송하지 않습니다.

실행:  python friday_gesture.py               (기본: 브라우저 탭 넘기기)
       python friday_gesture.py --mode window (창 전환)
       python friday_gesture.py --mode snap   (현재 창을 화면 왼쪽/오른쪽 절반으로)
       python friday_gesture.py --mode desktop(가상 데스크톱 이동)
       python friday_gesture.py --mode slide  (발표 슬라이드 넘기기)
옵션:  --camera 1  (카메라 번호)   --no-preview  (미리보기 창 없이)   --sens 0.2 (작을수록 민감)
미리보기 창에서: q 또는 Esc 종료, p 일시정지/재개
"""
import argparse
import os
import sys
import time
import urllib.request

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")

# 손짓 방향별 단축키. 오른쪽 손짓 = 오른쪽(다음), 왼쪽 손짓 = 왼쪽(이전)
MODES = {
    "tab": {"right": ["ctrl", "tab"], "left": ["ctrl", "shift", "tab"], "desc": "브라우저 탭 오른쪽/왼쪽"},
    "window": {"right": ["alt", "tab"], "left": ["alt", "shift", "tab"], "desc": "창 전환 (Alt+Tab)"},
    "snap": {"right": ["win", "right"], "left": ["win", "left"], "desc": "현재 창을 오른쪽/왼쪽 절반으로"},
    "desktop": {"right": ["ctrl", "win", "right"], "left": ["ctrl", "win", "left"], "desc": "가상 데스크톱 오른쪽/왼쪽"},
    "slide": {"right": ["right"], "left": ["left"], "desc": "슬라이드 다음/이전"},
}


class SwipeDetector:
    """좌우 손짓 판정. x는 거울 기준(사용자 오른쪽=1). Friday 웹 버전과 같은 규칙.

    - th: 0.5초 안에 화면 폭의 몇 % 이상 움직여야 손짓으로 볼지
    - 세로 이동이 가로의 60%를 넘으면 무시, 손바닥을 편 상태여야 함
    - 한 번 인식 후 0.9초 쉬고, 반대 방향(손을 되돌리는 동작)은 1.6초 동안 무시
    """

    def __init__(self, th=0.2, win=0.5, cd=0.9, opp=1.6, gap=0.3, op=0.4):
        self.th, self.win, self.cd, self.opp, self.gap, self.op = th, win, cd, opp, gap, op
        self.hs, self.last_t, self.last_d, self.seen, self.open_t = [], -9.0, 0, -9.0, -9.0

    def feed(self, t, x=None, y=None, is_open=False):
        if x is None:
            if t - self.seen > self.gap:
                self.hs = []
            return 0
        self.seen = t
        if is_open:
            self.open_t = t
        self.hs.append((t, x, y))
        while self.hs and t - self.hs[0][0] > self.win:
            self.hs.pop(0)
        if t - self.open_t > self.op or t - self.last_t < self.cd:
            return 0
        best, bd = None, 0.0
        for p in self.hs:
            d = x - p[1]
            if abs(d) > abs(bd):
                bd, best = d, p
        if best is None or abs(bd) < self.th:
            return 0
        if abs(y - best[2]) > 0.6 * abs(bd) or t - best[0] < 0.06:
            return 0
        d = 1 if bd > 0 else -1
        if d == -self.last_d and t - self.last_t < self.opp:
            return 0
        self.last_t, self.last_d, self.hs = t, d, []
        return d


def hand_open(p):
    def dist(a, b):
        return ((p[a].x - p[b].x) ** 2 + (p[a].y - p[b].y) ** 2) ** 0.5
    n = sum(1 for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)) if dist(tip, 0) > dist(pip, 0) * 1.15)
    return n >= 3


def hand_center(p):
    idx = (0, 5, 9, 13, 17)
    return 1 - sum(p[i].x for i in idx) / 5, sum(p[i].y for i in idx) / 5


# ---- 키 입력 (Windows 기본 기능만 사용, 추가 설치 불필요) ----
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "tab": 0x09, "left": 0x25, "right": 0x27}
EXTENDED = {"left", "right", "win"}


def press(keys):
    if sys.platform != "win32":
        print("  (Windows가 아니라 키 입력은 생략:", "+".join(keys), ")")
        return
    import ctypes
    ke = ctypes.windll.user32.keybd_event
    for k in keys:
        ke(VK[k], 0, 1 if k in EXTENDED else 0, 0)
        time.sleep(0.02)
    for k in reversed(keys):
        ke(VK[k], 0, (1 if k in EXTENDED else 0) | 2, 0)
        time.sleep(0.02)


def ensure_model():
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        return
    print("손 인식 모델을 내려받습니다 (약 8MB, 처음 한 번만)...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("완료:", MODEL_PATH)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="프라이데이 손짓 제어")
    ap.add_argument("--mode", choices=list(MODES), default="tab")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--sens", type=float, default=0.2, help="손짓 거리 기준(화면 폭 비율, 기본 0.2)")
    a = ap.parse_args()

    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    ensure_model()
    opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
    )
    cap = cv2.VideoCapture(a.camera, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(a.camera)
    if not cap.isOpened():
        print("카메라를 열지 못했습니다. 다른 프로그램이 쓰고 있거나 번호가 다릅니다 (--camera 1 시도).")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    m = MODES[a.mode]
    det = SwipeDetector(th=a.sens)
    paused, msg, msg_t, t0 = False, "", 0.0, time.monotonic()
    print(f"시작: {m['desc']}  |  손바닥을 펴고 오른쪽/왼쪽으로 치우세요.  종료: 미리보기 창에서 q, 또는 Ctrl+C")
    with vision.HandLandmarker.create_from_options(opts) as lm:
        last_ts = -1
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()
                ts = int((now - t0) * 1000)
                if ts <= last_ts:
                    ts = last_ts + 1
                last_ts = ts
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                p = res.hand_landmarks[0] if res.hand_landmarks else None
                if p is None:
                    det.feed(now)
                else:
                    x, y = hand_center(p)
                    d = det.feed(now, x, y, hand_open(p))
                    if d and not paused:
                        side = "right" if d > 0 else "left"
                        press(m[side])
                        msg, msg_t = ("오른쪽 →" if d > 0 else "← 왼쪽") + "  " + "+".join(m[side]), now
                        print(time.strftime("%H:%M:%S"), msg)
                if not a.no_preview:
                    view = cv2.flip(frame, 1)
                    h, w = view.shape[:2]
                    if p is not None:
                        for q in p:
                            cv2.circle(view, (int((1 - q.x) * w), int(q.y * h)), 3, (255, 188, 141), -1)
                    status = "PAUSED (p)" if paused else a.mode.upper()
                    cv2.putText(view, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 220, 180), 1, cv2.LINE_AA)
                    if now - msg_t < 1.2:
                        arrow = "-->" if "오른쪽" in msg else "<--"
                        cv2.putText(view, arrow, (w // 2 - 40, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.imshow("Friday gesture (q: quit, p: pause)", view)
                    k = cv2.waitKey(1) & 0xFF
                    if k in (ord("q"), 27):
                        break
                    if k == ord("p"):
                        paused = not paused
                        print("일시정지" if paused else "재개")
        except KeyboardInterrupt:
            pass
    cap.release()
    if not a.no_preview:
        cv2.destroyAllWindows()
    print("종료했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
