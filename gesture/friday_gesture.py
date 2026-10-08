"""프라이데이 손짓 제어 (Windows)

웹캠으로 손을 인식해서 마우스와 단축키를 대신 조작합니다.
영상은 이 컴퓨터 안에서만 처리하며 저장하거나 전송하지 않습니다.

손동작
  검지만 세우기          커서 이동 (손 전체를 움직이면 커서가 따라옴)
  엄지+검지 집기         왼쪽 클릭 / 집은 채로 움직이면 드래그 / 빠르게 두 번이면 더블클릭
  검지+중지 V            위아래로 움직여 스크롤
  V 상태에서 엄지+중지   오른쪽 클릭
  손바닥 펴고 옆으로     단축키 (기본: 브라우저 탭 오른쪽/왼쪽, --mode 로 변경)
  주먹 1초 유지          일시정지 / 재개 (일시정지 중에는 아무것도 누르지 않음)

실행:  python friday_gesture.py                  (마우스 + 탭 넘기기)
       python friday_gesture.py --mode snap      (손바닥 손짓을 창 스냅으로)
       python friday_gesture.py --no-mouse       (손바닥 손짓만 사용)
옵션:  --camera 1   --no-preview   --sens 0.2 (손짓 거리)   --speed 1.0 (커서 속도)
미리보기 창에서: q 또는 Esc 종료, p 일시정지/재개
"""
import argparse
import math
import os
import sys
import time
import urllib.request

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")

# 손바닥 손짓 방향별 단축키. 오른쪽 손짓 = 오른쪽(다음), 왼쪽 손짓 = 왼쪽(이전)
MODES = {
    "tab": {"right": ["ctrl", "tab"], "left": ["ctrl", "shift", "tab"], "desc": "브라우저 탭 오른쪽/왼쪽"},
    "window": {"right": ["alt", "tab"], "left": ["alt", "shift", "tab"], "desc": "창 전환 (Alt+Tab)"},
    "snap": {"right": ["win", "right"], "left": ["win", "left"], "desc": "현재 창을 오른쪽/왼쪽 절반으로"},
    "desktop": {"right": ["ctrl", "win", "right"], "left": ["ctrl", "win", "left"], "desc": "가상 데스크톱 오른쪽/왼쪽"},
    "slide": {"right": ["right"], "left": ["left"], "desc": "슬라이드 다음/이전"},
    "media": {"right": ["next_track"], "left": ["prev_track"], "desc": "음악 다음 곡/이전 곡"},
}


# ---------------- 판정 도구 ----------------
class SwipeDetector:
    """좌우 손짓 판정. x는 거울 기준(사용자 오른쪽=1). Friday 웹 버전과 같은 규칙.
    0.5초 안에 화면 폭의 th 이상 가로로 이동 + 손바닥 편 상태. 인식 후 0.9초 휴지,
    반대 방향(손 되돌리기)은 1.6초 무시."""

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


class OneEuro:
    """커서 떨림 보정 (One Euro Filter, Casiez et al. 2012): 천천히 움직이면 강하게, 빠르면 약하게 보정."""

    def __init__(self, mincut=1.2, beta=8.0, dcut=1.0):
        self.mincut, self.beta, self.dcut = mincut, beta, dcut
        self.x = self.dx = self.t = None

    @staticmethod
    def _a(cut, dt):
        tau = 1.0 / (2 * math.pi * cut)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t, x):
        if self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = t - self.t
        dx = (x - self.x) / dt
        self.dx += self._a(self.dcut, dt) * (dx - self.dx)
        cut = self.mincut + self.beta * abs(self.dx)
        self.x += self._a(cut, dt) * (x - self.x)
        self.t = t
        return self.x

    def reset(self):
        self.x = self.dx = self.t = None


def _d(p, a, b):
    return math.hypot(p[a].x - p[b].x, p[a].y - p[b].y)


def fingers(p):
    """검지·중지·약지·소지가 펴졌는지 (끝마디가 손목에서 둘째 마디보다 충분히 멀면 펴짐)."""
    return tuple(_d(p, tip, 0) > _d(p, pip, 0) * 1.15 for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)))


def hand_open(p):
    return sum(fingers(p)) >= 3


def hand_center(p):
    idx = (0, 5, 9, 13, 17)
    return 1 - sum(p[i].x for i in idx) / 5, sum(p[i].y for i in idx) / 5


def classify(p):
    """자세 판별. 반환: fist / pinch / v / open / point / other, 그리고 보조 값."""
    size = max(_d(p, 0, 9), 1e-6)
    ext = fingers(p)
    pin_i = _d(p, 4, 8) / size
    pin_m = _d(p, 4, 12) / size
    fist = not any(ext) and _d(p, 8, 0) / size < 1.15 and _d(p, 12, 0) / size < 1.15
    v = ext[0] and ext[1] and not ext[2] and not ext[3]
    if fist:
        pose = "fist"
    elif v:
        pose = "v"
    elif sum(ext) >= 4:
        pose = "open"
    elif ext[0] and not ext[1]:
        pose = "point"
    else:
        pose = "other"
    return pose, pin_i, pin_m, size


# ---------------- 입력 장치 ----------------
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "tab": 0x09, "left": 0x25, "right": 0x27,
      "next_track": 0xB0, "prev_track": 0xB1}
EXTENDED = {"left", "right", "win", "next_track", "prev_track"}


class WinOut:
    """Windows 기본 기능(user32)만 사용. 추가 설치 불필요."""

    def __init__(self):
        import ctypes
        self.u = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                self.u.SetProcessDPIAware()
            except Exception:
                pass
        self.W, self.H = self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def move(self, x, y):
        self.u.SetCursorPos(int(x), int(y))

    def button(self, which, down):
        flag = {("left", True): 0x02, ("left", False): 0x04, ("right", True): 0x08, ("right", False): 0x10}[(which, down)]
        self.u.mouse_event(flag, 0, 0, 0, 0)

    def wheel(self, notches):
        self.u.mouse_event(0x0800, 0, 0, int(notches * 120), 0)

    def keys(self, ks):
        for k in ks:
            self.u.keybd_event(VK[k], 0, 1 if k in EXTENDED else 0, 0)
            time.sleep(0.02)
        for k in reversed(ks):
            self.u.keybd_event(VK[k], 0, (1 if k in EXTENDED else 0) | 2, 0)
            time.sleep(0.02)

    def beep(self, up=True):
        try:
            import winsound
            winsound.Beep(1200 if up else 600, 90)
        except Exception:
            pass


class LogOut:
    """Windows가 아닐 때(시험용): 실제 입력 대신 기록만 남김."""

    def __init__(self, W=1920, H=1080):
        self.W, self.H, self.log, self.pos = W, H, [], (0, 0)

    def move(self, x, y):
        self.pos = (int(x), int(y))

    def button(self, which, down):
        self.log.append((which, "down" if down else "up"))

    def wheel(self, n):
        self.log.append(("wheel", n))

    def keys(self, ks):
        self.log.append(("keys", "+".join(ks)))

    def beep(self, up=True):
        pass


# ---------------- 제어기 ----------------
class Controller:
    PIN_ON, PIN_OFF = 0.28, 0.42     # 집기 판정(손바닥 길이 대비), 히스테리시스
    FREEZE = 0.25                    # 클릭 직후 커서 고정 시간(초) - 클릭 중 커서 흔들림 방지
    FIST_HOLD = 1.0                  # 일시정지 전환에 필요한 주먹 유지 시간
    SCROLL_STEP = 0.035              # 화면 높이 대비 이만큼 움직이면 한 칸 스크롤

    def __init__(self, out, mode="tab", mouse=True, sens=0.2, speed=1.0, region=(0.18, 0.15, 0.82, 0.75)):
        self.out, self.mode, self.mouse, self.speed = out, MODES[mode], mouse, speed
        self.region = region
        self.swipe = SwipeDetector(th=sens)
        self.fx, self.fy = OneEuro(), OneEuro()
        self.paused = False
        self.left_down = False
        self.down_t = 0.0
        self.right_pinch = False
        self.fist_t = None
        self.fist_used = False
        self.scroll_y = None
        self.scroll_acc = 0.0
        self.no_scroll_until = 0.0
        self.state = "-"
        self.msg, self.msg_t = "", -9.0

    def _say(self, t, m):
        self.msg, self.msg_t = m, t
        print(time.strftime("%H:%M:%S"), m)

    def _cursor(self, t, p):
        x0, y0, x1, y1 = self.region
        rx = 1 - p[5].x                              # 검지 뿌리 관절: 집을 때도 덜 흔들림
        ry = p[5].y
        cx = (rx - 0.5) * self.speed + 0.5
        cy = (ry - 0.5) * self.speed + 0.5
        nx = min(1, max(0, (cx - x0) / (x1 - x0)))
        ny = min(1, max(0, (cy - y0) / (y1 - y0)))
        sx, sy = self.fx(t, nx * (self.out.W - 1)), self.fy(t, ny * (self.out.H - 1))
        self.out.move(sx, sy)

    def release_all(self):
        if self.left_down:
            self.out.button("left", False)
            self.left_down = False
        self.right_pinch = False
        self.scroll_y = None

    def update(self, t, p):
        if p is None:
            self.release_all()
            self.fist_t, self.fist_used = None, False
            self.fx.reset(); self.fy.reset()
            self.swipe.feed(t)
            self.state = "-"
            return
        pose, pin_i, pin_m, size = classify(p)

        # 주먹 1초 → 일시정지/재개 (일시정지 중에도 동작)
        if pose == "fist" and not self.left_down:
            if self.fist_t is None:
                self.fist_t = t
            elif not self.fist_used and t - self.fist_t >= self.FIST_HOLD:
                self.paused = not self.paused
                self.fist_used = True
                self.release_all()
                self.out.beep(not self.paused)
                self._say(t, "일시정지" if self.paused else "재개")
        else:
            self.fist_t, self.fist_used = None, False
        if self.paused:
            self.state = "PAUSED"
            return
        if pose == "fist":
            self.state = "FIST"
            self.release_all()
            return

        # 손바닥 좌우 손짓 → 단축키
        x, y = hand_center(p)
        d = self.swipe.feed(t, x, y, pose == "open")
        if d:
            self.release_all()
            side = "right" if d > 0 else "left"
            self.out.keys(self.mode[side])
            self._say(t, ("오른쪽 →  " if d > 0 else "←  왼쪽  ") + "+".join(self.mode[side]))
            self.state = "SWIPE"
            return

        if not self.mouse:
            self.state = pose.upper()
            return

        # V: 스크롤, 엄지+중지 → 오른쪽 클릭
        if pose == "v" and not self.left_down:
            if not self.right_pinch and pin_m < self.PIN_ON:
                self.right_pinch = True
                self.out.button("right", True)
                self.out.button("right", False)
                self.no_scroll_until = t + 0.5
                self.scroll_y = None
                self._say(t, "오른쪽 클릭")
            elif self.right_pinch and pin_m > self.PIN_OFF:
                self.right_pinch = False
            if t >= self.no_scroll_until and not self.right_pinch:
                yy = p[9].y
                if self.scroll_y is None:
                    self.scroll_y, self.scroll_acc = yy, 0.0
                self.scroll_acc += (self.scroll_y - yy) / self.SCROLL_STEP   # 손을 올리면 위로 스크롤
                self.scroll_y = yy
                n = int(self.scroll_acc)
                if n:
                    self.out.wheel(n)
                    self.scroll_acc -= n
            self.state = "SCROLL"
            return
        self.scroll_y = None
        self.right_pinch = False

        # 엄지+검지 집기 → 왼쪽 버튼 누름/뗌 (짧게 = 클릭, 유지하며 이동 = 드래그)
        if not self.left_down and pin_i < self.PIN_ON and pose in ("point", "other"):
            self.left_down, self.down_t = True, t
            self.out.button("left", True)
        elif self.left_down and pin_i > self.PIN_OFF:
            self.left_down = False
            self.out.button("left", False)
            self._say(t, "클릭" if t - self.down_t < 0.4 else "드래그 끝")

        if self.left_down:
            if t - self.down_t >= self.FREEZE:
                self._cursor(t, p)
            self.state = "DRAG" if t - self.down_t >= self.FREEZE else "CLICK"
            return
        if pose in ("point", "other"):
            self._cursor(t, p)
            self.state = "POINT"
        else:
            self.state = pose.upper()


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
    ap.add_argument("--mode", choices=list(MODES), default="tab", help="손바닥 좌우 손짓에 연결할 단축키")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--no-mouse", action="store_true", help="마우스 조작 끄기 (손바닥 손짓만)")
    ap.add_argument("--sens", type=float, default=0.2, help="손짓 거리 기준(화면 폭 비율, 기본 0.2)")
    ap.add_argument("--speed", type=float, default=1.0, help="커서 속도 배율 (기본 1.0, 크게 하면 작은 움직임으로 화면 끝까지)")
    a = ap.parse_args()

    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    out = WinOut() if sys.platform == "win32" else LogOut()
    ensure_model()
    opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    cap = cv2.VideoCapture(a.camera, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(a.camera)
    if not cap.isOpened():
        print("카메라를 열지 못했습니다. 다른 프로그램(Friday 손동작, 화상회의 등)이 쓰고 있거나 번호가 다릅니다 (--camera 1 시도).")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    ctl = Controller(out, mode=a.mode, mouse=not a.no_mouse, sens=a.sens, speed=a.speed)
    t0 = time.monotonic()
    print(f"시작 | 마우스 {'켜짐' if ctl.mouse else '꺼짐'} | 손바닥 손짓: {MODES[a.mode]['desc']}")
    print("검지=커서, 엄지+검지 집기=클릭/드래그, V=스크롤, V에서 엄지+중지=우클릭, 주먹 1초=일시정지. 종료: 미리보기 창에서 q 또는 Ctrl+C")
    with vision.HandLandmarker.create_from_options(opts) as lm:
        last_ts = -1
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()
                ts = max(int((now - t0) * 1000), last_ts + 1)
                last_ts = ts
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                p = res.hand_landmarks[0] if res.hand_landmarks else None
                ctl.update(now, p)
                if not a.no_preview:
                    view = cv2.flip(frame, 1)
                    h, w = view.shape[:2]
                    x0, y0, x1, y1 = ctl.region
                    cv2.rectangle(view, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (90, 70, 40), 1)
                    if p is not None:
                        for q in p:
                            cv2.circle(view, (int((1 - q.x) * w), int(q.y * h)), 3, (255, 188, 141), -1)
                    col = (80, 80, 255) if ctl.paused else (255, 220, 180)
                    cv2.putText(view, ctl.state, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 1, cv2.LINE_AA)
                    if now - ctl.msg_t < 1.2 and ("→" in ctl.msg or "←" in ctl.msg):
                        arrow = "-->" if "→" in ctl.msg else "<--"
                        cv2.putText(view, arrow, (w // 2 - 40, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.imshow("Friday gesture (q: quit, p: pause)", view)
                    k = cv2.waitKey(1) & 0xFF
                    if k in (ord("q"), 27):
                        break
                    if k == ord("p"):
                        ctl.paused = not ctl.paused
                        ctl.release_all()
                        print("일시정지" if ctl.paused else "재개")
        except KeyboardInterrupt:
            pass
        finally:
            ctl.release_all()
    cap.release()
    if not a.no_preview:
        cv2.destroyAllWindows()
    print("종료했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
