# Portable launcher entry point. All orchestration lives in start.py so the
# PowerShell wrapper never duplicates host/port defaults; it only selects an
# interpreter (VOLUNTEER_PYTHON, bundled project env, then PATH).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$pythonExe = $null
$pythonPrefix = @()
$projectPython = Join-Path $PSScriptRoot '.conda/envs/volunteer-core/python.exe'
if ($env:VOLUNTEER_PYTHON -and (Test-Path -LiteralPath $env:VOLUNTEER_PYTHON)) {
    $pythonExe = $env:VOLUNTEER_PYTHON
} elseif (Test-Path -LiteralPath $projectPython) {
    $pythonExe = $projectPython
} else {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        $pythonExe = $command.Source
    } else {
        $command = Get-Command py -ErrorAction SilentlyContinue
        if (-not $command) {
            Write-Host '未找到可用的 Python。'
            Write-Host '请安装 Python 3.10 或更新版本并执行 python -m pip install -r requirements.txt，'
            Write-Host '或设置环境变量 VOLUNTEER_PYTHON 指向已安装依赖的解释器。'
            exit 1
        }
        $pythonExe = $command.Source
        $pythonPrefix = @('-3')
    }
}

& $pythonExe @pythonPrefix -X utf8 (Join-Path $PSScriptRoot 'start.py') @args
exit $LASTEXITCODE
