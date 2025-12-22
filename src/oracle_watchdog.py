#!/usr/bin/env python3
"""Oracle Bot Watchdog - Monitors and restarts services, sends alerts"""

import subprocess
import time
import requests
import json
import os
from datetime import datetime

# Config
TELEGRAM_BOT_TOKEN = "8574423634:AAGC-6ZH_Vmvo-8lF7OniQfp1xiekqTuuDo"
TELEGRAM_CHAT_ID = "618aborting187676"
CHECK_INTERVAL = 30  # seconds
LOG_FILE = "/tmp/watchdog.log"

SERVICES = {
    "data_puller": {
        "cmd": "python3 -u /home/vibhavaggarwal/data_puller.py",
        "log": "/tmp/data_puller.log",
        "check_log_age": 60,  # Alert if log not updated in 60s
    },
    "oracle_bot": {
        "cmd": "python3 -u /home/vibhavaggarwal/oracle_bot.py", 
        "log": "/tmp/oracle_bot.log",
        "check_log_age": 60,
    }
}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def send_telegram(msg):
    """Send alert to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": f"🤖 ORACLE BOT ALERT\n\n{msg}", "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
        log(f"Telegram sent: {msg[:50]}...")
    except Exception as e:
        log(f"Telegram failed: {e}")

def is_process_running(name):
    """Check if process is running"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False

def get_log_age(log_file):
    """Get age of log file in seconds"""
    try:
        mtime = os.path.getmtime(log_file)
        return time.time() - mtime
    except:
        return 9999

def start_service(name, config):
    """Start a service"""
    log(f"Starting {name}...")
    try:
        subprocess.Popen(
            config["cmd"],
            shell=True,
            stdout=open(config["log"], "a"),
            stderr=subprocess.STDOUT,
            cwd="/home/vibhavaggarwal",
            start_new_session=True
        )
        time.sleep(3)
        if is_process_running(name):
            log(f"{name} started successfully")
            return True
        else:
            log(f"{name} failed to start")
            return False
    except Exception as e:
        log(f"Error starting {name}: {e}")
        return False

def check_health():
    """Check all services health"""
    issues = []
    
    for name, config in SERVICES.items():
        # Check if running
        if not is_process_running(name):
            issues.append(f"❌ {name} NOT RUNNING")
            log(f"{name} not running, restarting...")
            if start_service(name, config):
                issues[-1] += " → Restarted ✅"
            else:
                issues[-1] += " → Restart FAILED ❌"
        
        # Check log freshness
        log_age = get_log_age(config["log"])
        if log_age > config["check_log_age"]:
            issues.append(f"⚠️ {name} log stale ({int(log_age)}s old)")
    
    # Check cache file
    cache_age = get_log_age("/tmp/oracle_ticker_cache.json")
    if cache_age > 30:
        issues.append(f"⚠️ Ticker cache stale ({int(cache_age)}s old)")
    
    return issues

def get_status():
    """Get current status summary"""
    status = []
    for name, config in SERVICES.items():
        running = "✅" if is_process_running(name) else "❌"
        log_age = int(get_log_age(config["log"]))
        status.append(f"{name}: {running} (log: {log_age}s)")
    return " | ".join(status)

def main():
    log("=" * 50)
    log("ORACLE WATCHDOG STARTED")
    log("=" * 50)
    send_telegram("🟢 Watchdog started - monitoring Oracle Bot")
    
    last_alert_time = 0
    alert_cooldown = 300  # 5 min between alerts
    
    while True:
        try:
            issues = check_health()
            
            if issues:
                log(f"Issues found: {issues}")
                
                # Send alert (with cooldown)
                if time.time() - last_alert_time > alert_cooldown:
                    send_telegram("\n".join(issues))
                    last_alert_time = time.time()
            else:
                log(f"All OK: {get_status()}")
            
        except Exception as e:
            log(f"Watchdog error: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
