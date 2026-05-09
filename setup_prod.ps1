# PRC AI Hub - Production Pre-Push Build Script
# Run this locally before every push to Render to ensure fresh frontend assets.

param(
    [switch]$SkipInstall  # Pass -SkipInstall to skip npm install if deps are unchanged
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$frontendDir = Join-Path $projectRoot "frontend"
$distIndex   = Join-Path $frontendDir "dist\index.html"

Write-Host "PRC AI Hub - Production Build" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

# ── 1. Node / npm check ────────────────────────────────────────────────────────
Write-Host "`n[1/4] Checking Node.js..." -ForegroundColor Yellow
if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js not found. Install from https://nodejs.org and re-run."
    exit 1
}
Write-Host "      Node $(node --version)  |  npm $(npm --version)" -ForegroundColor Gray

# ── 2. Install frontend deps ───────────────────────────────────────────────────
if (-not $SkipInstall) {
    Write-Host "`n[2/4] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install --prefer-offline 2>&1 | Select-String -NotMatch "^npm warn"
    Pop-Location
} else {
    Write-Host "`n[2/4] Skipping npm install (-SkipInstall flag set)." -ForegroundColor Gray
}

# ── 3. Build React app ─────────────────────────────────────────────────────────
Write-Host "`n[3/4] Building React frontend (Vite production build)..." -ForegroundColor Yellow
Push-Location $frontendDir
npm run build
Pop-Location

if (!(Test-Path $distIndex)) {
    Write-Error "Build failed - frontend/dist/index.html not found."
    exit 1
}
Write-Host "      Build successful." -ForegroundColor Green

# ── 4. Print git commands ──────────────────────────────────────────────────────
Write-Host "`n[4/4] Ready to push. Run the following git commands:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  git add app.py simulation_core.py requirements.txt render.yaml setup_prod.ps1" -ForegroundColor White
Write-Host "  git add hermes_skills_library/petroleum/simulator/simulation_core.py" -ForegroundColor White
Write-Host "  git add frontend/dist/" -ForegroundColor White
Write-Host "  git status" -ForegroundColor White
Write-Host "  git commit -m 'chore: production hardening + fresh frontend build'" -ForegroundColor White
Write-Host "  git push origin main" -ForegroundColor White
Write-Host ""
Write-Host "Render will auto-deploy on push. Monitor at: https://dashboard.render.com" -ForegroundColor Cyan
