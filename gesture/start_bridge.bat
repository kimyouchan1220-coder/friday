@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Friday 노트북 연결 프로그램
set PY=
where python >nul 2>nul && set PY=python
if not defined PY (where py >nul 2>nul && set PY=py -3)
if not defined PY (echo Python을 찾지 못했습니다. https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe 를 설치하고, 첫 화면의 "Add python.exe to PATH"를 체크하세요. & pause & exit /b 1)
%PY% friday_bridge.py %*
pause
