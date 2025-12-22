#!/usr/bin/env python3
"""
Oracle Auto-Healer - Self-repairing and self-improving system
- Detects errors and fixes them automatically
- Optimizes performance based on metrics
- Reports all actions to Telegram
"""

import subprocess
import time
import requests
import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

# Config
TELEGRAM_BOT_TOKEN = "8574423634:AAGC-6ZH_Vmvo-8lF7OniQfp1xiekqTuuDo"
TELEGRAM_CHAT_ID = "1088402136"
CHECK_INTERVAL = 30
LOG_FILE = "/tmp/autohealer.log"
METRICS_FILE = "/home/vibhavaggarwal/oracle_metrics.json"
BOT_FILE = "/home/vibhavaggarwal/oracle_bot.py"
DATA_PULLER_FILE = "/home/vibhavaggarwal/data_puller.py"

# Known error patterns and their fixes
ERROR_FIXES = {
    "ConnectionError": {
        "pattern": r"ConnectionError|Connection refused|Connection reset",
        "fix": "restart_service",
        "service": "oracle-data-puller",
        "description": "Network connection issue - restarting data puller"
    },
    "JSONDecodeError": {
        "pattern": r"JSONDecodeError|Expecting value|json.decoder",
        "fix": "clear_cache",
        "description": "Corrupted cache - clearing and restarting"
    },
    "MemoryError": {
        "pattern": r"MemoryError|Cannot allocate memory|Out of memory",
        "fix": "restart_all",
        "description": "Memory issue - restarting all services"
    },
    "RateLimitError": {
        "pattern": r"429|rate limit|too many requests",
        "fix": "increase_delay",
        "description": "Rate limited - increasing API delay"
    },
    "TimeoutError": {
        "pattern": r"TimeoutError|timed out|timeout",
        "fix": "increase_timeout",
        "description": "Timeout - increasing timeout values"
    },
    "AttributeError": {
        "pattern": r"AttributeError|has no attribute",
        "fix": "log_and_report",
        "description": "Code bug detected - logging for review"
    },
    "ZeroDivisionError": {
        "pattern": r"ZeroDivisionError|division by zero",
        "fix": "add_safety_check",
        "description": "Division error - adding safety check"
    },
    "KeyError": {
        "pattern": r"KeyError",
        "fix": "log_and_report", 
        "description": "Missing key - logging for review"
    }
}

# Performance thresholds
PERF_THRESHOLDS = {
    "scan_time_ms": 200,      # Max acceptable scan time
    "cache_age_s": 5,         # Max cache staleness
    "memory_pct": 80,         # Max memory usage
    "error_rate_pct": 5,      # Max error rate
    "update_rate_min": 10     # Min updates per minute
}

class AutoHealer:
    def __init__(self):
        self.metrics = self.load_metrics()
        self.error_counts = defaultdict(int)
        self.fixes_applied = []
        self.last_report = time.time()
        
    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    
    def send_telegram(self, msg, urgent=False):
        try:
            prefix = "🚨 URGENT" if urgent else "🔧 AUTO-HEALER"
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": f"{prefix}\n\n{msg}", "parse_mode": "HTML"}
            requests.post(url, data=data, timeout=10)
        except:
            pass
    
    def load_metrics(self):
        try:
            with open(METRICS_FILE, "r") as f:
                return json.load(f)
        except:
            return {"scans": [], "errors": [], "fixes": [], "performance": []}
    
    def save_metrics(self):
        # Keep only last 1000 entries
        for key in self.metrics:
            if isinstance(self.metrics[key], list):
                self.metrics[key] = self.metrics[key][-1000:]
        with open(METRICS_FILE, "w") as f:
            json.dump(self.metrics, f)
    
    def get_recent_errors(self, log_file, minutes=5):
        """Get errors from last N minutes"""
        errors = []
        try:
            result = subprocess.run(
                ["tail", "-500", log_file],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split("\n"):
                if any(x in line.lower() for x in ["error", "exception", "failed", "traceback"]):
                    errors.append(line)
        except:
            pass
        return errors
    
    def detect_error_pattern(self, errors):
        """Detect known error patterns"""
        detected = []
        error_text = "\n".join(errors)
        for name, config in ERROR_FIXES.items():
            if re.search(config["pattern"], error_text, re.IGNORECASE):
                detected.append((name, config))
        return detected
    
    # ============ FIX FUNCTIONS ============
    
    def restart_service(self, service):
        """Restart a specific service"""
        self.log(f"Restarting {service}...")
        subprocess.run(["sudo", "systemctl", "restart", service], timeout=30)
        time.sleep(5)
        result = subprocess.run(["sudo", "systemctl", "is-active", service], capture_output=True, text=True)
        return result.stdout.strip() == "active"
    
    def restart_all(self):
        """Restart all services"""
        self.log("Restarting all services...")
        for svc in ["oracle-data-puller", "oracle-bot"]:
            subprocess.run(["sudo", "systemctl", "restart", svc], timeout=30)
            time.sleep(3)
        return True
    
    def clear_cache(self):
        """Clear corrupted cache files"""
        self.log("Clearing cache files...")
        try:
            os.remove("/tmp/oracle_ticker_cache.json")
        except:
            pass
        self.restart_service("oracle-data-puller")
        return True
    
    def increase_delay(self):
        """Increase API delay to avoid rate limits"""
        self.log("Increasing API delay...")
        try:
            with open(DATA_PULLER_FILE, "r") as f:
                content = f.read()
            # Find and increase sleep values
            content = re.sub(r"time\.sleep\(0\.5\)", "time.sleep(1.0)", content)
            content = re.sub(r"time\.sleep\(0\.1\)", "time.sleep(0.2)", content)
            with open(DATA_PULLER_FILE, "w") as f:
                f.write(content)
            self.restart_service("oracle-data-puller")
            return True
        except Exception as e:
            self.log(f"Failed to increase delay: {e}")
            return False
    
    def increase_timeout(self):
        """Increase timeout values"""
        self.log("Increasing timeout values...")
        try:
            for filepath in [BOT_FILE, DATA_PULLER_FILE]:
                with open(filepath, "r") as f:
                    content = f.read()
                content = re.sub(r"timeout=5", "timeout=10", content)
                content = re.sub(r"timeout=10", "timeout=15", content)
                with open(filepath, "w") as f:
                    f.write(content)
            self.restart_all()
            return True
        except Exception as e:
            self.log(f"Failed to increase timeout: {e}")
            return False
    
    def add_safety_check(self):
        """Add safety checks for division errors"""
        self.log("This requires manual code review - logging issue")
        return False
    
    def log_and_report(self):
        """Log error for manual review"""
        return False
    
    # ============ PERFORMANCE OPTIMIZATION ============
    
    def get_performance_metrics(self):
        """Collect current performance metrics"""
        metrics = {}
        
        # Memory usage
        try:
            result = subprocess.run(["free", "-m"], capture_output=True, text=True)
            lines = result.stdout.split("\n")
            mem_line = [l for l in lines if l.startswith("Mem:")][0].split()
            metrics["memory_pct"] = int(mem_line[2]) / int(mem_line[1]) * 100
        except:
            metrics["memory_pct"] = 0
        
        # Cache age
        try:
            mtime = os.path.getmtime("/tmp/oracle_ticker_cache.json")
            metrics["cache_age_s"] = time.time() - mtime
        except:
            metrics["cache_age_s"] = 999
        
        # Update rate from data puller log
        try:
            result = subprocess.run(["tail", "-20", "/tmp/data_puller.log"], capture_output=True, text=True)
            updates = re.findall(r"Updates: D=(\d+)", result.stdout)
            if len(updates) >= 2:
                diff = int(updates[-1]) - int(updates[0])
                metrics["update_rate_min"] = diff * 3  # Approximate per minute
            else:
                metrics["update_rate_min"] = 0
        except:
            metrics["update_rate_min"] = 0
        
        # Error rate
        errors = self.get_recent_errors("/tmp/oracle_bot.log", 5)
        metrics["error_count"] = len(errors)
        
        return metrics
    
    def optimize_performance(self, metrics):
        """Apply optimizations based on metrics"""
        optimizations = []
        
        # High memory - clear old data
        if metrics.get("memory_pct", 0) > PERF_THRESHOLDS["memory_pct"]:
            self.log("High memory usage - clearing logs")
            subprocess.run("truncate -s 0 /tmp/oracle_bot.log", shell=True)
            optimizations.append("Cleared large log file")
        
        # Stale cache - restart data puller
        if metrics.get("cache_age_s", 0) > PERF_THRESHOLDS["cache_age_s"]:
            self.log("Stale cache detected - restarting data puller")
            self.restart_service("oracle-data-puller")
            optimizations.append("Restarted data puller for fresh cache")
        
        # Low update rate
        if metrics.get("update_rate_min", 999) < PERF_THRESHOLDS["update_rate_min"]:
            self.log("Low update rate - checking data puller")
            self.restart_service("oracle-data-puller")
            optimizations.append("Restarted data puller for better update rate")
        
        return optimizations
    
    # ============ SELF-IMPROVEMENT ============
    
    def analyze_trading_performance(self):
        """Analyze trading results and suggest improvements"""
        try:
            with open("/home/vibhavaggarwal/paper_state.json", "r") as f:
                state = json.load(f)
            
            wins = state.get("wins", 0)
            losses = state.get("losses", 0)
            total = wins + losses
            
            if total < 5:
                return None  # Not enough data
            
            win_rate = wins / total * 100
            avg_win = state.get("avg_win", 0)
            avg_loss = abs(state.get("avg_loss", 0))
            
            suggestions = []
            
            # Win rate too low
            if win_rate < 40:
                suggestions.append({
                    "issue": f"Low win rate: {win_rate:.1f}%",
                    "suggestion": "Increase confidence threshold",
                    "action": "increase_threshold"
                })
            
            # Risk/reward ratio poor
            if avg_loss > 0 and avg_win / avg_loss < 1.5:
                suggestions.append({
                    "issue": f"Poor R:R ratio: {avg_win/avg_loss:.2f}",
                    "suggestion": "Increase TP multiplier or decrease SL",
                    "action": "adjust_sl_tp"
                })
            
            # Too many consecutive losses
            if state.get("consecutive_losses", 0) >= 3:
                suggestions.append({
                    "issue": "3+ consecutive losses",
                    "suggestion": "Pause trading, increase threshold",
                    "action": "pause_and_adjust"
                })
            
            return suggestions
        except:
            return None
    
    def apply_trading_improvement(self, action):
        """Apply trading improvements"""
        try:
            with open(BOT_FILE, "r") as f:
                content = f.read()
            
            if action == "increase_threshold":
                # Increase confidence threshold
                content = re.sub(
                    r"CONFIDENCE_THRESHOLD\s*=\s*(\d+)",
                    lambda m: f"CONFIDENCE_THRESHOLD = {int(m.group(1)) + 5}",
                    content
                )
                self.log("Increased confidence threshold by 5")
                
            elif action == "adjust_sl_tp":
                # Increase TP multiplier
                content = re.sub(
                    r"ATR_TP_MULTIPLIER\s*=\s*([\d.]+)",
                    lambda m: f"ATR_TP_MULTIPLIER = {float(m.group(1)) + 0.5}",
                    content
                )
                self.log("Increased TP multiplier by 0.5")
                
            elif action == "pause_and_adjust":
                content = re.sub(
                    r"CONFIDENCE_THRESHOLD\s*=\s*(\d+)",
                    lambda m: f"CONFIDENCE_THRESHOLD = {int(m.group(1)) + 10}",
                    content
                )
                self.log("Significantly increased threshold after losses")
            
            with open(BOT_FILE, "w") as f:
                f.write(content)
            
            self.restart_service("oracle-bot")
            return True
        except Exception as e:
            self.log(f"Failed to apply improvement: {e}")
            return False
    
    # ============ MAIN LOOP ============
    
    def run_check(self):
        """Run a single health check cycle"""
        actions_taken = []
        
        # 1. Check for errors and apply fixes
        for log_file in ["/tmp/oracle_bot.log", "/tmp/data_puller.log"]:
            errors = self.get_recent_errors(log_file)
            if errors:
                detected = self.detect_error_pattern(errors)
                for name, config in detected:
                    self.error_counts[name] += 1
                    
                    # Only fix if error persists (seen 3+ times)
                    if self.error_counts[name] >= 3:
                        self.log(f"Applying fix for {name}: {config[description]}")
                        
                        fix_func = getattr(self, config["fix"], None)
                        if fix_func:
                            if config.get("service"):
                                success = fix_func(config["service"])
                            else:
                                success = fix_func()
                            
                            if success:
                                actions_taken.append(f"✅ Fixed: {config[description]}")
                                self.error_counts[name] = 0
                            else:
                                actions_taken.append(f"⚠️ Manual fix needed: {config[description]}")
        
        # 2. Performance optimization
        metrics = self.get_performance_metrics()
        optimizations = self.optimize_performance(metrics)
        actions_taken.extend([f"⚡ {o}" for o in optimizations])
        
        # 3. Trading performance analysis (every 10 minutes)
        if time.time() - self.last_report > 600:
            suggestions = self.analyze_trading_performance()
            if suggestions:
                for s in suggestions:
                    self.log(f"Trading suggestion: {s[suggestion]}")
                    if self.apply_trading_improvement(s["action"]):
                        actions_taken.append(f"📈 Applied: {s[suggestion]}")
            self.last_report = time.time()
        
        # 4. Report actions
        if actions_taken:
            report = "\n".join(actions_taken)
            self.send_telegram(f"Actions taken:\n{report}")
            self.log(f"Actions: {actions_taken}")
        
        # 5. Save metrics
        self.metrics["performance"].append({
            "ts": time.time(),
            "metrics": metrics,
            "actions": len(actions_taken)
        })
        self.save_metrics()
        
        return actions_taken
    
    def run(self):
        """Main loop"""
        self.log("=" * 50)
        self.log("ORACLE AUTO-HEALER STARTED")
        self.log("=" * 50)
        self.send_telegram("🟢 Auto-Healer started\n\nFeatures:\n• Error detection & auto-fix\n• Performance optimization\n• Trading strategy improvement")
        
        while True:
            try:
                self.run_check()
            except Exception as e:
                self.log(f"Check error: {e}", "ERROR")
            
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    healer = AutoHealer()
    healer.run()
