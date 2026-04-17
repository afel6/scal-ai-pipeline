# 🏟 PRC AI Pipeline: "Always-On" Production Handbook

A guide to moving the **n8n Orchestration Layer** from a testing machine to a permanent, 24/7 sovereign server.

## 1. Choosing the Hardware
To make the system "always there," you need a machine that never turns off.

### Option A: The "Sovereign" Mini-PC (Recommended)
Buy a small dedicated computer (Intel NUC or similar) and place it in the PRC IT room.
- **Spec**: 4GB+ RAM, 50GB+ SSD.
- **Benefit**: 100% physical sovereignty. Data never leaves the Libyan building.

### Option B: Private Virtual Server (VPS)
Rent a server from a provider like DigitalOcean or Hetzner.
- **Spec**: Standard 2-CPU / 4GB RAM plan (~$15/mo).
- **Benefit**: 99.9% uptime and easily accessible by experts globally.

## 2. One-Click Deployment
Once you have your server (Windows with PowerShell or Linux with Docker), follow these steps:

1.  Clone the repository to the server.
2.  Open PowerShell as Administrator.
3.  Run: 
    ```powershell
    ./setup_prod.ps1
    ```
    This script will automatically configure the database, n8n, and the secure expert tunnel.

## 3. Persistent Access (Standardizing the URL)
For the testing phase, the tunnel gives you a `trycloudflare.com` URL. For a **permanent** setup:
1.  Sign up for a free **Cloudflare** account.
2.  Add a domain (e.g., `prc-ai.org`).
3.  Create a permanent "Named Tunnel" in your `docker-compose.yaml` (I can help you with this once you have the domain).

## 4. Maintenance & Security
- **Restarts**: The `docker-compose.yaml` is set to `restart: always`. If the power cuts and the server reboots, the AI Hub will come back online automatically.
- **Credentials**: Ensure the `1509` administrative password is changed for the final production deployment.

---
*PRC Engineering Hub — Production Readiness v2.2*
