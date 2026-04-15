# =========================
# Autonomous SDLC Setup Script (Windows)
# Installs Backend (Python) + Frontend (Node/React)
# Run from repo root:  .\setup.ps1
# =========================

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " Autonomous SDLC - Full Setup (Backend + UI)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# --- 1) Backend: Python venv + requirements ---
Write-Host "`n[1/2] Setting up Backend (Python)..." -ForegroundColor Yellow

if (!(Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Green
    python -m venv .venv
}

Write-Host "Activating virtual environment..." -ForegroundColor Green
. .\.venv\Scripts\Activate

Write-Host "Upgrading pip..." -ForegroundColor Green
python -m pip install --upgrade pip

if (Test-Path "requirements.txt") {
    Write-Host "Installing backend dependencies from requirements.txt..." -ForegroundColor Green
    pip install -r requirements.txt
} else {
    Write-Host "ERROR: requirements.txt not found in repo root." -ForegroundColor Red
    exit 1
}

# --- 2) Frontend: npm install ---
Write-Host "`n[2/2] Setting up Frontend (React)..." -ForegroundColor Yellow

if (Test-Path "ui\\ui-app\\package.json") {
    Push-Location "ui\\ui-app"
    Write-Host "Installing frontend dependencies (npm install)..." -ForegroundColor Green
    npm install
    Pop-Location
} else {
    Write-Host "WARNING: ui\\ui-app\\package.json not found. Skipping frontend install." -ForegroundColor DarkYellow
}

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host " Setup Completed Successfully ✅" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`nNext Commands:" -ForegroundColor White
Write-Host "Backend:  python -m uvicorn app.core.config:app --reload --host 127.0.0.1 --port 5000" -ForegroundColor Gray
Write-Host "Frontend: cd ui\\ui-app; npm run dev  (or npm start if CRA)" -ForegroundColor Gray