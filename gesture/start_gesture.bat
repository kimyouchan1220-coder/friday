@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
rem py 실행 도우미를 먼저 씀: PATH 체크를 안 해도 되고, Windows의 가짜 python(스토어 연결)을 피함
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (echo Python을 찾지 못했습니다. https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe 를 설치하고, 첫 화면의 "Add python.exe to PATH"를 체크하세요. & pause & exit /b 1)
%PY% -c "import mediapipe" 2>nul || (echo 처음 실행: 손 인식 라이브러리를 설치합니다. 몇 분 걸립니다... & %PY% -m pip install --upgrade mediapipe)
%PY% friday_gesture.py %*
pause
