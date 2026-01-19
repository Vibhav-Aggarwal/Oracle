# Oracle Trading System - Complete Development Workflow

**Date:** 2026-01-19
**Status:** ✅ ACTIVE & AUTOMATED

---

## 🎯 Workflow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  ORACLE DEVELOPMENT WORKFLOW                     │
│         (Laptop → GitHub → Cloud → Resources)                    │
└─────────────────────────────────────────────────────────────────┘

1. DEVELOPMENT (Laptop)
   ├── ~/Projects/production/oracle/
   ├── Write code, test locally
   └── Commit to Git

2. VERSION CONTROL (GitHub)
   ├── Repository: https://github.com/Vibhav-Aggarwal/Oracle.git
   ├── Trigger: Push to main branch
   └── GitHub Actions workflow starts

3. AUTOMATED DEPLOYMENT (GitHub Actions)
   ├── Test: Lint + Unit tests
   ├── Deploy to: Oracle Cloud Server (92.4.88.143)
   └── Health check verification

4. PRODUCTION (Cloud Server)
   ├── Location: /home/ubuntu/Projects/production/oracle
   ├── Pull latest code
   ├── Restart service
   └── Verify health

5. RESOURCES (Connected Systems)
   ├── Lab Server (10.0.0.192) - Production trading
   ├── Admin Server (10.0.0.74) - ML training
   ├── GPU Server (10.0.0.71) - Compute
   └── k3s Cluster - Orchestration
```

---

## 📝 Step-by-Step Usage

### 1. Development on Laptop

```bash
# Navigate to project
cd ~/Projects/production/oracle

# Make changes to code
vim src/main.py

# Test locally (optional)
python src/main.py

# Check status
git status
```

### 2. Commit & Push to GitHub

```bash
# Add changes
git add .

# Commit with meaningful message
git commit -m "feat: add new trading strategy"

# Push to GitHub (triggers deployment)
git push origin main
```

### 3. Automated Deployment (GitHub Actions)

GitHub Actions automatically:
- ✅ Runs linting (ruff)
- ✅ Runs unit tests (pytest)
- ✅ Deploys to Oracle Cloud Server
- ✅ Restarts oracle-bot service
- ✅ Verifies health check

**View Progress:**
- GitHub Actions: https://github.com/Vibhav-Aggarwal/Oracle/actions

### 4. Verify Deployment

```bash
# Check deployment status
ssh oracle-cloud "sudo systemctl status oracle-bot"

# View logs
ssh oracle-cloud "tail -f /home/ubuntu/Projects/production/oracle/logs/oracle_bot.log"

# Check health
curl http://92.4.88.143:8080/health
```

---

## 🔧 Server Configuration

### Oracle Cloud Server (92.4.88.143)

| Property | Value |
|----------|-------|
| **Hostname** | vibhav-cloud-server |
| **OS** | Ubuntu 24.04 LTS |
| **Kernel** | 6.14.0-1017-oracle |
| **SSH Key** | ~/.ssh/id_ed25519_vibhav |
| **SSH Alias** | `ssh oracle-cloud` |
| **Project Path** | /home/ubuntu/Projects/production/oracle |

### GitHub Repository

| Property | Value |
|----------|-------|
| **URL** | https://github.com/Vibhav-Aggarwal/Oracle.git |
| **Branch** | main |
| **CI/CD** | GitHub Actions |
| **Workflow** | .github/workflows/deploy.yml |

### Connected Resources

**Lab Server (10.0.0.192)**
- Role: Production trading execution
- Bots: delta_websocket_v10, delta_auto, oracle_bot, oracle_autohealer
- Uptime: 301+ hours (12+ days)
- Status: ✅ OPERATIONAL

**Admin Server (10.0.0.74)**
- Role: ML training hub (CUDA + GTX 970M)
- Services: MLflow (port 5000), ML training cron
- ML Sync: Every 6 hours → Lab Server
- Status: ✅ OPERATIONAL

**GPU Server (10.0.0.71)**
- Role: Mining + ML inference
- GPUs: 4x AMD RX 570 4GB
- Mining: TeamRedMiner (Ergo @ ~1.3 MH/s)
- Status: ✅ OPERATIONAL

**k3s Cluster**
- Master: Office Server (10.0.0.176)
- Agents: Lab, Admin, GPU Servers
- Version: v1.33.6+k3s1
- Status: ✅ ALL NODES READY

---

## 🚀 Quick Commands

### Development

```bash
# Start development
cd ~/Projects/production/oracle

# Run locally with test mode
python src/main.py

# Commit and deploy
git add . && git commit -m "feat: description" && git push
```

### Cloud Server Management

```bash
# SSH to Cloud Server
ssh oracle-cloud

# Check service status
ssh oracle-cloud "sudo systemctl status oracle-bot"

# View logs
ssh oracle-cloud "tail -f /home/ubuntu/Projects/production/oracle/logs/oracle_bot.log"

# Restart service (manual)
ssh oracle-cloud "sudo systemctl restart oracle-bot"

# Emergency stop
ssh oracle-cloud "sudo systemctl stop oracle-bot"
```

### Resource Server Access

```bash
# Lab Server (production trading)
ssh lab-server

# Admin Server (ML training)
ssh admin-server

# GPU Server (compute)
ssh gpu-server

# Office Server (k3s master)
ssh office-server
```

### Check Complete Ecosystem

```bash
# All k3s nodes
ssh -t office-server "echo 'Rama1994#' | sudo -S k3s kubectl get nodes"

# All trading bots (Lab Server)
ssh lab-server "ps aux | grep python | grep -E 'delta|oracle'"

# ML training status (Admin Server)
ssh admin-server "crontab -l | grep train_and_sync"

# GPU mining (GPU Server)
ssh gpu-server "ps aux | grep teamredminer"
```

---

## 🔐 Access & Credentials

### SSH Access

**Universal SSH Key:** `~/.ssh/id_ed25519_vibhav`
- Used by: All servers (Laptop, Home, Office, Lab, Admin, GPU, Cloud)
- Public Key: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILibL1rCreAT/aa+dOLhiI+9KxnDczuOdMh3Qcs9wfMu`

**SSH Aliases (from ~/.ssh/config):**
```
oracle-cloud   → 92.4.88.143 (Oracle Cloud)
home-server    → home-server.vibhavaggarwal.com
office-server  → office-server.vibhavaggarwal.com
lab-server     → lab-server.vibhavaggarwal.com
admin-server   → admin-server.vibhavaggarwal.com
gpu-server     → gpu-server.vibhavaggarwal.com
```

### GitHub Secrets

These secrets are configured in GitHub repository settings for automated deployment:

| Secret Name | Purpose |
|-------------|---------|
| `ORACLE_CLOUD_SSH_KEY` | SSH private key for deployment |
| `DISCORD_WEBHOOK` | Deployment notifications (optional) |

---

## 📊 Workflow States

### Development States

1. **Local Development** 🟡
   - Code changes on laptop
   - Local testing (optional)
   - Git commit

2. **Version Control** 🔵
   - Push to GitHub main branch
   - Triggers GitHub Actions

3. **CI/CD Running** ⚙️
   - Linting in progress
   - Tests running
   - Deployment executing

4. **Deployed** 🟢
   - Code on Cloud Server
   - Service restarted
   - Health check passed

5. **Failed** 🔴
   - Tests failed OR
   - Deployment error OR
   - Health check failed
   - Check GitHub Actions logs

---

## 🔍 Monitoring & Logs

### GitHub Actions

**View Deployment Status:**
- URL: https://github.com/Vibhav-Aggarwal/Oracle/actions
- Shows: Test results, deployment logs, errors

### Cloud Server Logs

```bash
# Application logs
ssh oracle-cloud "tail -f /home/ubuntu/Projects/production/oracle/logs/oracle_bot.log"

# Service logs
ssh oracle-cloud "sudo journalctl -u oracle-bot -f"

# System logs
ssh oracle-cloud "tail -f /var/log/syslog"
```

### Lab Server Logs (Production)

```bash
# Delta Websocket bot
ssh lab-server "tail -f ~/oracle-production/logs/delta_websocket_v10.log"

# Delta Auto bot
ssh lab-server "tail -f ~/oracle-production/logs/delta_auto.log"

# Oracle main bot
ssh lab-server "tail -f ~/oracle_bot.log"
```

---

## 🛡️ Safety & Rollback

### Rollback Procedure

If deployment fails or causes issues:

```bash
# 1. SSH to Cloud Server
ssh oracle-cloud

# 2. Navigate to project
cd /home/ubuntu/Projects/production/oracle

# 3. Check git log
git log --oneline -5

# 4. Rollback to previous commit
git reset --hard HEAD~1

# 5. Restart service
sudo systemctl restart oracle-bot

# 6. Verify health
curl -f http://localhost:8080/health
```

### Emergency Stop

```bash
# Stop Cloud Server bot
ssh oracle-cloud "sudo systemctl stop oracle-bot"

# Stop ALL Lab Server bots (if needed)
ssh lab-server "pkill -f 'python.*oracle' && pkill -f 'python.*delta'"
```

---

## 📈 Resource Utilization

### Current Allocation

| Server | Role | Resources | Status |
|--------|------|-----------|--------|
| **Laptop** | Development | Local | Active |
| **Cloud** | Backup/Testing | 1 vCPU, 1GB RAM | Active |
| **Lab** | Production Trading | 8 cores, 3GB RAM | 4 bots running |
| **Admin** | ML Training | 4 cores, 8GB, GPU | Training every 6h |
| **GPU** | Mining + Compute | 4x RX 570 | Mining active |
| **Office** | k3s Master | 4 cores, 8GB | Cluster running |

### Network Topology

```
Internet
    │
    ├─── Oracle Cloud (92.4.88.143)
    │    └─── Oracle Bot (backup/testing)
    │
    └─── Home Network (192.168.1.x)
         └─── Home Server
              └─── Cloudflare Tunnels
                   └─── Office Network (10.0.0.x)
                        ├─── Office Server (k3s master)
                        ├─── Lab Server (production trading)
                        ├─── Admin Server (ML training)
                        └─── GPU Server (mining + compute)
```

---

## 🎯 Best Practices

### Before Pushing Code

1. ✅ Test locally if possible
2. ✅ Write meaningful commit messages
3. ✅ Check git status before committing
4. ✅ Review changes with `git diff`

### After Deployment

1. ✅ Check GitHub Actions (green checkmark)
2. ✅ Verify service status on Cloud Server
3. ✅ Monitor logs for 5-10 minutes
4. ✅ Check health endpoint

### For Production Changes

⚠️ **CRITICAL:** Production trading bots run on Lab Server, NOT Cloud Server

If making changes that affect production:
1. Test on Cloud Server first
2. Monitor Cloud Server for 24 hours
3. Only then deploy to Lab Server manually
4. Never auto-deploy to Lab Server (real money!)

---

## 📞 Quick Reference

### Essential URLs

| Resource | URL |
|----------|-----|
| **GitHub Repo** | https://github.com/Vibhav-Aggarwal/Oracle.git |
| **GitHub Actions** | https://github.com/Vibhav-Aggarwal/Oracle/actions |
| **Cloud Console** | https://cloud.oracle.com/?region=ap-mumbai-1 |
| **Cloud Health** | http://92.4.88.143:8080/health |

### Essential Commands

```bash
# Deploy
git push origin main

# Check deployment
ssh oracle-cloud "sudo systemctl status oracle-bot"

# View logs
ssh oracle-cloud "tail -f /home/ubuntu/Projects/production/oracle/logs/oracle_bot.log"

# Rollback
ssh oracle-cloud "cd /home/ubuntu/Projects/production/oracle && git reset --hard HEAD~1 && sudo systemctl restart oracle-bot"

# Check all systems
ssh -t office-server "echo 'Rama1994#' | sudo -S k3s kubectl get nodes"
```

---

## ✅ System Status

**Development Workflow:** ✅ ACTIVE
**GitHub Actions:** ✅ CONFIGURED
**Cloud Server:** ✅ OPERATIONAL
**Resource Servers:** ✅ ALL READY
**k3s Cluster:** ✅ 4/4 NODES READY

**Last Updated:** 2026-01-19 22:45 IST
**Status:** Production-ready with full automation
**Next Review:** As needed

---

**Happy Trading! 🚀📈**
