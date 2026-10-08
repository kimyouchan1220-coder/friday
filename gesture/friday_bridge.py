"""프라이데이 노트북 연결 프로그램 (Windows)

Friday 웹사이트가 "디스코드 켜줘 / 꺼줘" 같은 명령을 이 프로그램에 보내면, 이 컴퓨터에서 앱을 열고 닫습니다.

보안
- 이 컴퓨터 안(127.0.0.1)에서만 접속을 받습니다. 다른 기기에서는 접속할 수 없습니다.
- Friday 사이트(https://kimyouchan1220-coder.github.io)에서 온 요청만 받습니다.
- 처음 한 번 콘솔에 나오는 6자리 연결 코드로 짝을 맺어야 하고, 이후에는 그때 받은 비밀 토큰이 있어야 합니다.
- 임의의 명령은 실행하지 않습니다. 바탕화면·시작 메뉴 바로가기와 정해 둔 Windows 기본 앱만 열고 닫습니다.
- 시스템 프로세스와 웹 브라우저(Friday가 그 안에서 돌기 때문)는 끄지 않습니다.

실행: start_bridge.bat (또는 python friday_bridge.py)
옵션: --reset  연결을 초기화(기존 토큰 무효)하고 새 코드 발급
"""
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0"
HOST, PORT = "127.0.0.1", 47213
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "bridge_token.txt")
FRIDAY_ORIGIN = "https://kimyouchan1220-coder.github.io"
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")  # 이 컴퓨터에서 직접 연 Friday 사본(시험용)
BAD_URI = re.compile(r"^(javascript|data|file|vbscript|ms-msdt|search-ms|search|ms-officecmd|ms-appinstaller|shell|ms-cxh|ms-cxh-full|res|mk|its|ms-its|hcp|jar|blob):", re.I)
OK_URI = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)

# 끄면 안 되는 것: 시스템, 이 프로그램 자신, 브라우저(Friday가 꺼짐)
PROTECTED = {"explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "services.exe", "smss.exe",
             "wininit.exe", "dwm.exe", "system", "registry", "fontdrvhost.exe", "sihost.exe", "taskhostw.exe",
             "python.exe", "pythonw.exe", "py.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
             "windowsterminal.exe", "update.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe"}
BROWSERS = {"chrome.exe", "msedge.exe", "whale.exe", "firefox.exe", "opera.exe", "brave.exe"}

# 한국어로 부르는 이름 → 바로가기 이름
ALIASES = {"디스코드": "discord", "카톡": "카카오톡", "kakaotalk": "카카오톡", "크롬": "google chrome", "구글크롬": "google chrome",
           "엣지": "microsoft edge", "라이엇": "riot client", "라이엇클라이언트": "riot client", "롤": "league of legends",
           "리그오브레전드": "league of legends", "발로란트": "valorant", "클로드": "Claude", "스팀": "steam",
           "로블록스": "roblox player", "옵지지": "op.gg", "오피지지": "op.gg", "깃허브코파일럿": "github copilot",
           "엔비디아": "nvidia app", "메모장": "notepad", "그림판": "paint", "탐색기": "파일 탐색기", "파일탐색기": "파일 탐색기"}
# 바로가기가 없는 Windows 기본 앱: 여는 주소와 끌 때 찾을 실행 파일
BUILTIN = {
    "계산기": {"open": "calculator:", "exe": ["CalculatorApp.exe", "Calculator.exe"]},
    "날씨": {"open": "msnweather:", "exe": ["Microsoft.Msn.Weather.exe"]},
    "설정": {"open": "ms-settings:", "exe": ["SystemSettings.exe"]},
    "윈도우설정": {"open": "ms-settings:", "exe": ["SystemSettings.exe"]},
    "사진": {"open": "ms-photos:", "exe": ["Photos.exe"]},
    "시계": {"open": "ms-clock:", "exe": ["Time.exe"]},
    "알람": {"open": "ms-clock:", "exe": ["Time.exe"]},
    "카메라": {"open": "microsoft.windows.camera:", "exe": ["WindowsCamera.exe"]},
    "메일": {"open": "mailto:", "exe": ["olk.exe", "HxOutlook.exe"]},
    "스토어": {"open": "ms-windows-store://home/", "exe": ["WinStore.App.exe"]},
    "Claude": {"open": "claude://claude.ai/new", "exe": ["claude.exe"]},
    "메모장": {"open": "notepad.exe", "exe": ["Notepad.exe"]},
}
# 라이엇 런처 바로가기의 --launch-product 값 → 게임 프로세스
PRODUCTS = {"league_of_legends": ["LeagueClient.exe", "LeagueClientUx.exe", "LeagueClientUxRender.exe", "League of Legends.exe"],
            "valorant": ["VALORANT-Win64-Shipping.exe", "VALORANT.exe"]}
# 실행 파일 하나로 여러 프로세스가 뜨는 앱: 끌 때 같이 끌 이름
COMPANIONS = {"riotclientservices.exe": ["Riot Client.exe", "RiotClientUx.exe", "RiotClientUxRender.exe", "RiotClientServices.exe"],
              "leagueclient.exe": ["LeagueClient.exe", "LeagueClientUx.exe", "LeagueClientUxRender.exe"]}


def jo(w, a, b):
    """받침에 따라 조사 선택: 카카오톡을 / 디스코드를"""
    c = (w or " ")[-1]
    if "가" <= c <= "힣":
        return w + (a if (ord(c) - 0xAC00) % 28 else b)
    return w + (b if c.lower() in "aeiouy" else a + "(" + b + ")")  # 영어 이름은 발음을 알 수 없어 병기


def norm(s):
    return re.sub(r"[\s\-_.·'’()\[\]]", "", (s or "").lower())


def apply_alias(q):
    n = norm(q)
    for k, v in ALIASES.items():
        if n == norm(k):
            return v
    return q


# ---------------- 운영체제 기능 (Windows) ----------------
class WinOS:
    def shortcut_dirs(self):
        e = os.environ.get
        dirs = [os.path.join(e("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
                os.path.join(e("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
                os.path.join(e("USERPROFILE", ""), "Desktop"), os.path.join(e("PUBLIC", r"C:\Users\Public"), "Desktop")]
        od = e("OneDrive")
        if od:
            dirs += [os.path.join(od, "Desktop"), os.path.join(od, "바탕 화면")]
        return [d for d in dirs if d and os.path.isdir(d)]

    def list_shortcuts(self):
        out = {}
        for d in self.shortcut_dirs():
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".lnk", ".url")):
                        name = os.path.splitext(f)[0]
                        if re.search(r"(uninstall|제거|삭제|readme|도움말|help)", name, re.I):
                            continue
                        out.setdefault(name, os.path.join(root, f))
        return out

    def shortcut_target(self, path):
        """(실행 파일 경로, 인수) — 바로가기(.lnk)만. PowerShell로 읽음."""
        if not path.lower().endswith(".lnk"):
            return "", ""
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:FRIDAY_LNK);"
              "Write-Output $s.TargetPath;Write-Output $s.Arguments")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               text=True, timeout=8, env={**os.environ, "FRIDAY_LNK": path}, creationflags=0x08000000)
            lines = (r.stdout or "").splitlines() + ["", ""]
            return lines[0].strip(), lines[1].strip()
        except Exception:
            return "", ""

    def start(self, target):
        os.startfile(target)  # 바로가기·주소를 Windows 기본 동작으로 실행 (더블클릭과 같음)

    def running(self, exe):
        try:
            r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"], capture_output=True,
                               text=True, timeout=8, creationflags=0x08000000)
            return exe.lower() in (r.stdout or "").lower()
        except Exception:
            return False

    def kill(self, exe, force):
        args = ["taskkill", "/IM", exe] + (["/F", "/T"] if force else [])
        subprocess.run(args, capture_output=True, text=True, timeout=10, creationflags=0x08000000)


# ---------------- 앱 찾기·열기·끄기 ----------------
class Apps:
    def __init__(self, osx):
        self.os = osx
        self._sc, self._sc_t, self._tg = {}, 0.0, {}
        self.lock = threading.Lock()

    def shortcuts(self):
        with self.lock:
            if time.time() - self._sc_t > 60:
                self._sc, self._sc_t = self.os.list_shortcuts(), time.time()
            return self._sc

    def names(self):
        return sorted(set(list(self.shortcuts().keys()) + list(BUILTIN.keys())))

    def find(self, q):
        """이름 → ('builtin', 키) / ('lnk', 이름, 경로) / None"""
        q = apply_alias(q)
        n = norm(q)
        if not n:
            return None
        for k in BUILTIN:
            if norm(k) == n:
                return ("builtin", k)
        sc = self.shortcuts()
        cands = [(name, p) for name, p in sc.items()]
        for rule in (lambda m: m == n, lambda m: m.startswith(n), lambda m: n in m):
            hit = [(nm, p) for nm, p in cands if rule(norm(nm))]
            if hit:
                hit.sort(key=lambda x: (len(x[0]), not x[1].lower().endswith(".lnk")))
                return ("lnk", hit[0][0], hit[0][1])
        return None

    def exes_for(self, found):
        if found[0] == "builtin":
            return BUILTIN[found[1]]["exe"]
        path = found[2]
        if path not in self._tg:
            self._tg[path] = self.os.shortcut_target(path)
        tgt, args = self._tg[path]
        exe = os.path.basename(tgt)
        m = re.search(r"--processStart\s+\"?([^\s\"]+\.exe)", args or "", re.I)  # 디스코드 등: Update.exe --processStart Discord.exe
        if m:
            exe = m.group(1)
        p = re.search(r"--launch-product=(\w+)", args or "", re.I)
        if p and p.group(1).lower() in PRODUCTS:
            return PRODUCTS[p.group(1).lower()]
        if not exe.lower().endswith(".exe"):
            return []
        return COMPANIONS.get(exe.lower(), [exe])

    def open(self, q):
        f = self.find(q)
        if not f:
            return False, f"이 컴퓨터에서 '{q}' 앱의 바로가기를 찾지 못했습니다."
        if f[0] == "builtin":
            self.os.start(BUILTIN[f[1]]["open"])
            return True, jo(f[1], "을", "를") + " 열었습니다."
        self.os.start(f[2])
        return True, jo(f[1], "을", "를") + " 열었습니다."

    def close(self, q, force=False):
        f = self.find(q)
        if not f:
            return False, f"이 컴퓨터에서 '{q}' 앱을 찾지 못했습니다."
        label = f[1]
        exes = self.exes_for(f)
        if not exes:
            return False, jo(label, "은", "는") + " 실행 파일을 알 수 없어 끌 수 없습니다."
        low = [e.lower() for e in exes]
        if any(e in BROWSERS for e in low):
            return False, jo(label, "은", "는") + " 웹 브라우저라 끄지 않습니다. Friday도 함께 꺼지기 때문입니다."
        if any(e in PROTECTED for e in low):
            return False, jo(label, "은", "는") + " 시스템에 필요한 프로그램이라 끄지 않습니다."
        live = [e for e in exes if self.os.running(e)]
        if not live:
            return True, jo(label, "은", "는") + " 실행 중이 아닙니다."
        for e in live:
            self.os.kill(e, force)
        if not force:  # 정상 종료 요청 후 3초 안에 안 꺼지면 강제 종료 (트레이로 숨는 앱 대비)
            for _ in range(6):
                time.sleep(0.5)
                if not any(self.os.running(e) for e in live):
                    break
            rest = [e for e in live if self.os.running(e)]
            for e in rest:
                self.os.kill(e, True)
        left = [e for e in live if self.os.running(e)]
        if left:
            return False, jo(label, "을", "를") + " 끄지 못했습니다. 관리자 권한으로 실행 중인 앱일 수 있습니다."
        return True, jo(label, "을", "를") + " 종료했습니다."


# ---------------- 연결(짝 맺기) ----------------
class Auth:
    def __init__(self, reset=False):
        self.token = None
        if not reset and os.path.exists(TOKEN_FILE):
            self.token = open(TOKEN_FILE, encoding="utf-8").read().strip() or None
        self.new_code()

    def new_code(self):
        self.code, self.code_t, self.fails = f"{secrets.randbelow(10**6):06d}", time.time(), 0

    def pair(self, code):
        if time.time() - self.code_t > 600:
            self.new_code()
            show_code(self)
            return None
        if not secrets.compare_digest(str(code), self.code):
            self.fails += 1
            if self.fails >= 5:
                self.new_code()
                show_code(self)
            return None
        if not self.token:
            self.token = secrets.token_urlsafe(32)
            try:
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(self.token)
            except OSError:
                pass
        self.new_code()
        return self.token

    def ok(self, tok):
        return bool(self.token and tok and secrets.compare_digest(tok, self.token))


def show_code(auth):
    print(f"\n  연결 코드: {auth.code}   (Friday에 '노트북 연결 {auth.code}'라고 말하거나 입력, 10분 유효)\n", flush=True)


def make_handler(apps, auth, log=print):
    class H(BaseHTTPRequestHandler):
        server_version = "FridayBridge/" + VERSION

        def log_message(self, *a):
            pass

        def _origin_ok(self):
            o = self.headers.get("Origin", "")
            return o == FRIDAY_ORIGIN or bool(LOCAL_ORIGIN.match(o))

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            o = self.headers.get("Origin", "")
            if self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if not self._origin_ok():
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin"))
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Friday-Token")
            self.send_header("Access-Control-Allow-Private-Network", "true")  # 크롬의 내부망 접근 확인 대응
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def _body(self):
            try:
                n = min(int(self.headers.get("Content-Length", "0")), 4096)
                return json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return {}

        def _gate(self, need_token=True):
            if not self._origin_ok():
                self._send(403, {"error": "허용되지 않은 출처입니다."})
                return False
            if need_token and not auth.ok(self.headers.get("X-Friday-Token", "")):
                self._send(401, {"error": "연결되지 않았습니다. 프로그램 창의 연결 코드로 다시 연결하세요."})
                return False
            return True

        def do_GET(self):
            if self.path == "/ping":
                if not self._gate(False):
                    return
                return self._send(200, {"ok": True, "app": "friday-bridge", "version": VERSION,
                                        "paired": auth.ok(self.headers.get("X-Friday-Token", ""))})
            if self.path == "/apps":
                if not self._gate():
                    return
                return self._send(200, {"ok": True, "apps": apps.names()})
            self._send(404, {"error": "없는 경로"})

        def do_POST(self):
            b = self._body()
            if self.path == "/pair":
                if not self._gate(False):
                    return
                tok = auth.pair(str(b.get("code", "")).strip())
                if not tok:
                    return self._send(403, {"error": "연결 코드가 맞지 않거나 만료되었습니다. 프로그램 창의 새 코드를 확인하세요."})
                log("Friday와 연결되었습니다.")
                return self._send(200, {"ok": True, "token": tok})
            if not self._gate():
                return
            try:
                if self.path == "/open":
                    uri, app = (b.get("uri") or "").strip(), (b.get("app") or "").strip()[:60]
                    if uri:
                        if BAD_URI.match(uri) or not OK_URI.match(uri) or len(uri) > 2000:
                            return self._send(400, {"error": "보안상 열 수 없는 주소 형식입니다."})
                        apps.os.start(uri)
                        log(f"열기: {uri[:80]}")
                        return self._send(200, {"ok": True, "msg": "열었습니다."})
                    ok, msg = apps.open(app)
                    log(("열기: " if ok else "열기 실패: ") + app)
                    return self._send(200 if ok else 404, {"ok": ok, "msg": msg})
                if self.path == "/close":
                    app = (b.get("app") or "").strip()[:60]
                    ok, msg = apps.close(app, bool(b.get("force")))
                    log(("종료: " if ok else "종료 실패: ") + app + " / " + msg)
                    return self._send(200 if ok else 409, {"ok": ok, "msg": msg})
            except Exception as e:
                return self._send(500, {"error": f"처리 중 오류: {e}"})
            self._send(404, {"error": "없는 경로"})
    return H


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    reset = "--reset" in sys.argv
    if reset and os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    if sys.platform != "win32":
        print("이 프로그램은 Windows용입니다.")
        return 1
    auth = Auth(reset)
    apps = Apps(WinOS())
    try:
        srv = ThreadingHTTPServer((HOST, PORT), make_handler(apps, auth))
    except OSError:
        print(f"포트 {PORT}를 이미 쓰고 있습니다. 연결 프로그램이 이미 켜져 있는지 확인하세요.")
        return 1
    print(f"프라이데이 노트북 연결 프로그램 {VERSION} 실행 중 (이 컴퓨터 안에서만 접속 가능)")
    print(f"찾은 앱 바로가기: {len(apps.shortcuts())}개")
    if auth.token:
        print("이미 Friday와 연결된 적이 있습니다. 새로 연결하려면 아래 코드를 쓰세요.")
    show_code(auth)
    print("이 창을 닫으면 연결이 끊깁니다. 종료: Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("종료했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
