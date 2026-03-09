# Railway(또는 기타 서버)에서 저장한 category_table.json을 로컬 data/로 동기화
# 사용: .\sync_category_from_server.ps1
#       .\sync_category_from_server.ps1 -ServerUrl "https://본인도메인.up.railway.app"
# 서버 URL을 한 번만 설정하려면 아래 $DefaultServerUrl 값을 수정하세요.

param(
    [string] $ServerUrl = $env:SYNC_SERVER_URL
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not $ServerUrl) {
    Write-Host "사용법: .\sync_category_from_server.ps1 -ServerUrl ""https://본인도메인.up.railway.app"""
    Write-Host "  또는 환경변수: `$env:SYNC_SERVER_URL = ""https://..."" 후 인자 없이 실행"
    exit 1
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python readme/sync_category_from_server.py $ServerUrl
exit $LASTEXITCODE
