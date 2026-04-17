# PRC AI Hub: Production "Always-On" Setup Script
# This script initializes the sovereign AI infrastructure on a permanent server.

Write-Host "🚀 Initializing PRC AI Pipeline: Always-On Mode..." -ForegroundColor Cyan

# 1. Check for Docker
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "❌ Docker is not installed! Please install Docker Desktop or Docker Engine first."
    exit
}

# 2. Check for docker-compose
if (!(Get-Command docker-compose -ErrorAction SilentlyContinue)) {
    Write-Error "❌ docker-compose is not installed!"
    exit
}

# 3. Environment Check
if (!(Test-Path .env)) {
    Write-Warning "⚠️ .env file not found. Creating default production .env..."
    $envContent = @"
GEMINI_API_KEY=YOUR_KEY_HERE
CLAUDE_API_KEY=YOUR_KEY_HERE
DB_POSTGRES_USER=prc_user
DB_POSTGRES_PASSWORD=prc_password_1509
DB_POSTGRES_DATABASE=prc_hub
N8N_ENCRYPTION_KEY=prc_secret_key_1509
"@
    Set-Content -Path .env -Value $envContent
}

# 4. Launching Infrastructure
Write-Host "📦 Pulling images and starting containers..." -ForegroundColor Gray
docker-compose up -d

# 5. Verification
Write-Host "⏳ Waiting for database health-check..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

$status = docker ps --filter "name=prc-n8n" --format "{{.Status}}"
if ($status -like "*Up*") {
    Write-Host "✅ PRC AI Orchestrator is ONLINE." -ForegroundColor Green
    Write-Host "🔗 Local Access: http://localhost:5678"
    Write-Host "🔗 Remote Testing (via Tunnel):" -ForegroundColor Magenta
    docker logs prc-tunnel | Select-String "https://.*\.trycloudflare\.com" | Select-Object -First 1
} else {
    Write-Error "❌ Deployment failed. Check 'docker logs prc-n8n' for details."
}

Write-Host "`n🎯 Setup Complete. The server will now auto-restart on reboot." -ForegroundColor Cyan
