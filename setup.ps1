# Sets up Woots Editor on Windows: a private Python environment and a check of the programs it needs.
# Safe to run again. It never installs system software by itself: it prints the one command for each missing piece.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$os = [System.Environment]::OSVersion.Version
if ($os.Major -lt 10) { Write-Host "Woots Editor needs Windows 10 or 11."; exit 1 }

function Find-Python {
    foreach ($c in @(@("py", "-3.12"), @("python"), @("python3"))) {
        try {
            $v = & $c[0] $c[1..($c.Length - 1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.12") { return ,$c }
        } catch { }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.12 or newer was not found. Install it with:"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host "then run setup.bat again."
    exit 1
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the Python environment (.venv) ..."
    & $py[0] $py[1..($py.Length - 1)] -m venv .venv
}
$venvPy = ".venv\Scripts\python.exe"
Write-Host "Installing the packages (this can take a few minutes) ..."
if (Test-Path "requirements.lock") { & $venvPy -m pip install --require-hashes -r requirements.lock } else { & $venvPy -m pip install -r requirements.txt }
if ($LASTEXITCODE -ne 0) { Write-Host "Installing the packages failed."; exit 1 }
Write-Host "Installing the browser used to capture web pages as B-roll ..."
& $venvPy -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Host "The browser for web pages could not be installed: everything else works; run setup again later to add it." }

Write-Host ""
Write-Host "Checking the programs the app needs:"
$missing = $false
function Check($name, $ok, $fix) {
    if ($ok) { Write-Host "  ok       $name" } else { Write-Host "  MISSING  $name -> $fix"; $script:missing = $true }
}
Check "ffmpeg" ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command ffprobe -ErrorAction SilentlyContinue)) "winget install Gyan.FFmpeg"
$node = Get-Command node -ErrorAction SilentlyContinue
$nodeOk = $false
if ($node) { $nv = (& node --version) -replace "^v", ""; $nodeOk = [version]($nv -replace "^(\d+\.\d+).*", '$1') -ge [version]"22.0" }
Check "Node 22 or newer" $nodeOk "winget install OpenJS.NodeJS.LTS"
Check "Claude Code" ((Get-Command claude -ErrorAction SilentlyContinue) -or (Test-Path "$env:USERPROFILE\.local\bin\claude.exe")) "see https://claude.com/product/claude-code"
Write-Host ""
if ($missing) { Write-Host "Install what is missing, then run setup.bat again (the app also shows this list under Settings)." }
else { Write-Host "Everything is in place." }
Write-Host "Start the app with 'Start Woots Editor.bat'. Reading recordings on an Nvidia card needs one more step, offered in Settings."
