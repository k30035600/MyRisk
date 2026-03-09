@echo off
REM Cursor 밖에서 서버를 띄우면 localhost 연결이 됩니다. 이 배치 파일을 더블클릭하세요.
REM readme 폴더에서 상위(프로젝트 루트)로 이동 후 start-server.ps1 실행
cd /d "%~dp0\.."
start "MyRisk Server" powershell -NoExit -Command "& { chcp 65001 | Out-Null; $env:PYTHONUNBUFFERED='1'; Set-Location '%~dp0\..'; & '%~dp0start-server.ps1' }"
