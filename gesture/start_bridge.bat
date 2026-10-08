@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Friday 노트북 연결 프로그램
where python >nul 2>nul || (echo Python이 없습니다. https://www.python.org/downloads/ 에서 설치하고, 설치 첫 화면의 "Add python.exe to PATH"를 체크하세요. & pause & exit /b 1)
python friday_bridge.py %*
pause
