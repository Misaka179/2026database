$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
python scripts/local_mysql.py start
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m app.bootstrap
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
try {
    $runningApi = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/openapi.json' -TimeoutSec 2
    if ($runningApi.info.title -eq '图书馆志愿服务管理核心 API') {
        Write-Host 'API is already running: http://127.0.0.1:8765/docs'
        exit 0
    }
} catch {
    # No existing instance: start the API in this terminal.
}
Write-Host 'API: http://127.0.0.1:8765/docs'
python -m uvicorn app.api:app --host 127.0.0.1 --port 8765
