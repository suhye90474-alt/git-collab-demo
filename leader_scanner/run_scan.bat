@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title 주도주 스캐너

cd /d C:\myinvestapp\leader_scanner
if errorlevel 1 goto nofolder

if not defined KRX_ID goto noenv
if not defined KRX_PW goto noenv

python scan.py %*
goto end

:nofolder
echo [오류] C:\myinvestapp\leader_scanner 폴더를 찾을 수 없습니다.
goto end

:noenv
echo [안내] KRX 로그인 정보가 저장되어 있지 않습니다.
echo        먼저 setup_krx_env.bat 를 한 번 실행해서 아이디/비밀번호를 저장하세요.

:end
echo.
pause
