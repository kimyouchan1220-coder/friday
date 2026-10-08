@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 창 없는 파이썬(pyw)으로 연결 프로그램을 백그라운드에서 켬. 이 창은 바로 닫힘
set PYW=
where pyw >nul 2>nul && set "PYW=pyw -3"
if not defined PYW (where pythonw >nul 2>nul && set "PYW=pythonw")
if not defined PYW (echo Python을 찾지 못했습니다. https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe 를 설치하세요. & pause & exit /b 1)
start "" %PYW% "%~dp0friday_bridge.py" --hidden
