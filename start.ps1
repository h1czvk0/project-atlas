[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BackendRequirements = Join-Path $ProjectRoot "backend\requirements.txt"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExample = Join-Path $ProjectRoot ".env.example"

function Assert-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not available. $InstallHint"
    }
}

function Test-PortListening {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

Set-Location $ProjectRoot

Assert-Command "git" "Install Git and reopen PowerShell."
Assert-Command "node" "Install Node.js 20 or later."
Assert-Command "npm" "Make sure Node.js is installed correctly."

if (-not (Test-Path $EnvFile)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host "Created .env from .env.example. Add your model API settings to .env when needed." -ForegroundColor Yellow
}

if (-not (Test-Path $VenvPython)) {
    $PythonLauncher = Get-Command "python" -ErrorAction SilentlyContinue
    if (-not $PythonLauncher) {
        throw "Python is not available. Install Python 3.12 or later."
    }
    Write-Host "Creating the Python virtual environment..." -ForegroundColor Cyan
    & $PythonLauncher.Source -m venv (Join-Path $ProjectRoot ".venv")
}

if (-not $SkipInstall) {
    $BackendStamp = Join-Path $ProjectRoot ".venv\.atlas-requirements.sha256"
    $BackendHash = (Get-FileHash -LiteralPath $BackendRequirements -Algorithm SHA256).Hash
    $InstalledHash = if (Test-Path $BackendStamp) { (Get-Content -LiteralPath $BackendStamp -Raw).Trim() } else { "" }
    if ($BackendHash -ne $InstalledHash) {
        Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
        & $VenvPython -m pip install -r $BackendRequirements
        if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
        Set-Content -LiteralPath $BackendStamp -Value $BackendHash -NoNewline
    }

    if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) {
        Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
        Push-Location $FrontendRoot
        try {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        } finally {
            Pop-Location
        }
    }
}

$BackendRunning = Test-PortListening 8000
$FrontendRunning = Test-PortListening 5173

if (-not $BackendRunning) {
    $BackendCommand = "Set-Location '$ProjectRoot'; & '$VenvPython' -m uvicorn app.main:app --app-dir backend --reload"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BackendCommand) -WindowStyle Normal
    Write-Host "Backend is starting at http://127.0.0.1:8000" -ForegroundColor Green
} else {
    Write-Host "Port 8000 is already in use; keeping the existing backend." -ForegroundColor Yellow
}

if (-not $FrontendRunning) {
    $FrontendCommand = "Set-Location '$FrontendRoot'; npm run dev"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCommand) -WindowStyle Normal
    Write-Host "Frontend is starting at http://127.0.0.1:5173" -ForegroundColor Green
} else {
    Write-Host "Port 5173 is already in use; keeping the existing frontend." -ForegroundColor Yellow
}

if (-not $NoBrowser) {
    $Deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $Deadline) {
        try {
            $Response = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -eq 200) { break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    Start-Process "http://127.0.0.1:5173"
}

Write-Host "Project Atlas is ready. Close the two service windows to stop it." -ForegroundColor Green
