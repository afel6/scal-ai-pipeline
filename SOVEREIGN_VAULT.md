# Sovereign Vault: Data Integrity & Disaster Recovery
## Strategy for Hardening against GitHub Tampering & Infrastructure Outages

In response to the recent infrastructure attacks on major platforms (e.g., GitHub), we have implemented the **Sovereign Vault Strategy**. This ensures that your petrophysical data, simulation history, and codebase remain under your control even if cloud providers are compromised.

### 1. Cryptographic Identity (GPG Signing)
To ensure that no external entity can inject unauthorized changes into your codebase, all commits must be cryptographically signed.

**Action Required:**
1. Generate a GPG key: `gpg --full-generate-key`
2. Get the key ID: `gpg --list-secret-keys --keyid-format LONG`
3. Configure Git to use your key:
   ```powershell
   git config --global user.signingkey [YOUR_KEY_ID]
   git config --global commit.gpgsign true
   ```
4. Export your public key to GitHub/GitLab to get the "Verified" badge.

### 2. The Sovereign Vault Snapshot (`backup_vault.ps1`)
We have provided a custom script `backup_vault.ps1` that creates an immutable, timestamped archive of your entire environment.

**What it does:**
- **Code Bundling**: Creates a `.bundle` file containing the full Git history (compressed and portable).
- **Database Dump**: Extracts all chat history and analytics into a `.sql` file.
- **Environment Snapshot**: Backs up `.env` and `docker-compose.yaml`.
- **Zip Archive**: Compresses everything into a single file in the `vault_backups/` directory.

**How to use:**
Run this command periodically (e.g., once a week or before major demos):
```powershell
.\backup_vault.ps1
```

### 3. Redundancy Strategy (Multi-Remote)
Do not rely solely on GitHub. Add a second remote (e.g., a private GitLab instance or a local NAS).

**Action Required:**
```powershell
# Add a secondary vault remote
git remote add vault [URL_TO_NAS_OR_GITLAB]
# Push to both
git push origin master
git push vault master
```

### 4. Database Hardening
Your production data is stored in PostgreSQL (on Render). 
- **Automatic Backups**: Render/Neon provides daily snapshots.
- **Manual Off-site Backup**: You can run `pg_dump` locally using the `DATABASE_URL` from your Render environment variables to create a "Sovereign Copy" on your local machine.

---
**Status**: The pipeline is now hardened for executive demonstration. 
- **Persistence**: Fixed React hook regressions and email normalization.
- **Integrity**: GPG-ready.
- **Recovery**: `backup_vault.ps1` deployed.
