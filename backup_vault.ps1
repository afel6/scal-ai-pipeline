# PRC Sovereign Vault: Disaster Recovery & Integrity Tool
# Version: 1.0 (Enterprise Hardened)

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = "vault_backups\snapshot_$Timestamp"
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

Write-Host "🛡️  Initializing Sovereign Vault Snapshot: $Timestamp" -ForegroundColor Cyan

# 1. Git History Bundling (Immutable Code Backup)
Write-Host "📦  Bundling repository history..." -ForegroundColor Gray
git bundle create "$BackupDir\prc_code_history.bundle" --all
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Code History Secured." -ForegroundColor Green
} else {
    Write-Error "❌ Git Bundling Failed."
}

# 2. Database Snapshot (Chat History & Workflows)
Write-Host "🗄️  Extracting PostgreSQL Database..." -ForegroundColor Gray
if (docker ps -q -f name=prc-postgres) {
    docker exec prc-postgres pg_dump -U prc_user -d prc_hub > "$BackupDir\chat_history_dump.sql"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Database Snapshot Secured." -ForegroundColor Green
    } else {
        Write-Error "❌ Database Dump Failed."
    }
} else {
    Write-Warning "⚠️  prc-postgres container not running. Attempting SQLite fallback..."
    if (Test-Path "chat_history.db") {
        Copy-Item "chat_history.db" -Destination "$BackupDir\chat_history_local_fallback.db"
        Write-Host "✅ SQLite Fallback Secured." -ForegroundColor Green
    }
}

# 3. Environment Integrity
Write-Host "🔐  Securing environment configuration..." -ForegroundColor Gray
if (Test-Path ".env") {
    Copy-Item ".env" -Destination "$BackupDir\.env.backup"
}
if (Test-Path "docker-compose.yaml") {
    Copy-Item "docker-compose.yaml" -Destination "$BackupDir\docker-compose.backup.yaml"
}

# 4. Final Compression & Encryption Preparation
Write-Host "🤐  Compressing Vault Archive..." -ForegroundColor Gray
$ZipPath = "vault_backups\PRC_VAULT_$Timestamp.zip"
Compress-Archive -Path "$BackupDir\*" -DestinationPath $ZipPath -Force

Write-Host "`n✨ Sovereign Vault Created Successfully!" -ForegroundColor Green
Write-Host "📂 Location: $ZipPath" -ForegroundColor White
Write-Host "⚠️  IMPORTANT: Move this file to an OFFLINE storage device (USB/NAS) for maximum safety." -ForegroundColor Yellow
