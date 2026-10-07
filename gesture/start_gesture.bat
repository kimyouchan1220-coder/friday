@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo Python이 없습니다. https://www.python.org/downloads/ 에서 설치하고, 설치 첫 화면의 "Add python.exe to PATH"를 체크하세요. & pause & exit /b 1)
python -c "import mediapipe" 2>nul || (echo 처음 실행: 손 인식 라이브러리를 설치합니다. 몇 분 걸립니다... & python -m pip install --upgrade mediapipe)
python friday_gesture.py %*
pause
