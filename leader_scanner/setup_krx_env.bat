@echo off
chcp 65001 >nul
echo ============================================================
echo  KRX 로그인 정보를 사용자 환경변수(KRX_ID, KRX_PW)로 저장합니다.
echo  - data.krx.co.kr 에 가입한 계정을 입력하세요.
echo  - 비밀번호는 입력할 때 화면에 보이지 않습니다.
echo  - 저장 후 새로 여는 창/실행부터 적용됩니다 (run_scan.bat 은 바로 적용).
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$id = Read-Host 'KRX ID'; $s = Read-Host 'KRX Password' -AsSecureString; $pw = [System.Net.NetworkCredential]::new('', $s).Password; if (-not $id -or -not $pw) { Write-Host 'Canceled: empty input'; exit 1 }; [Environment]::SetEnvironmentVariable('KRX_ID', $id, 'User'); [Environment]::SetEnvironmentVariable('KRX_PW', $pw, 'User'); Write-Host 'Saved.'"

if errorlevel 1 (
    echo.
    echo [취소] 저장하지 않았습니다.
) else (
    echo.
    echo [완료] 저장했습니다. 이제 run_scan.bat 을 실행하세요.
)
echo.
pause
