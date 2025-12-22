#!/usr/bin/env python3
"""Oracle Trading Dashboard with Mode Switching"""

from flask import Flask, render_template, jsonify, send_from_directory, request
import json
import os
import subprocess
from datetime import datetime

app = Flask(__name__)

STATE_FILE = "/home/vibhavaggarwal/oracle_state.json"
MODE_FILE = "/home/vibhavaggarwal/trading_mode.json"

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading state: {e}")
    return {"balance": 1000, "positions": {}, "trades": [], "total_pnl": 0}

def load_mode():
    try:
        if os.path.exists(MODE_FILE):
            with open(MODE_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"mode": "paper", "switched_at": None}

def save_mode(mode_data):
    try:
        with open(MODE_FILE, 'w') as f:
            json.dump(mode_data, f)
        return True
    except Exception as e:
        print(f"Error saving mode: {e}")
        return False

def get_service_status(service_name):
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == 'active'
    except:
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/api/mode', methods=['GET'])
def get_mode():
    mode_data = load_mode()
    return jsonify(mode_data)

@app.route('/api/mode', methods=['POST'])
def set_mode():
    data = request.get_json()
    new_mode = data.get('mode', 'paper')
    
    if new_mode not in ['paper', 'live']:
        return jsonify({"error": "Invalid mode"}), 400
    
    mode_data = {
        "mode": new_mode,
        "switched_at": datetime.now().isoformat(),
        "switched_by": "dashboard"
    }
    
    if save_mode(mode_data):
        # Send Telegram notification about mode change
        try:
            import requests
            token = "8574423634:AAGC-6ZH_Vmvo-8lF7OniQfp1xiekqTuuDo"
            chat_id = "1088402136"
            emoji = "🟢" if new_mode == "live" else "🟡"
            msg = f"{emoji} <b>Trading Mode Changed</b>\n\nMode: <code>{new_mode.upper()}</code>\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
        except:
            pass
        
        return jsonify({"success": True, "mode": new_mode})
    else:
        return jsonify({"error": "Failed to save mode"}), 500

@app.route('/api/status')
def api_status():
    state = load_state()
    mode_data = load_mode()
    trades = state.get('trades', [])
    
    positions_dict = state.get('positions', {})
    positions = []
    if isinstance(positions_dict, dict):
        for key, pos in positions_dict.items():
            if isinstance(pos, dict):
                positions.append(pos)
    
    wins = state.get('wins', 0)
    losses = state.get('losses', 0)
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    metrics = {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "avg_win": round(state.get('avg_win', 0), 2),
        "avg_loss": round(abs(state.get('avg_loss', 0)), 2),
        "profit_factor": round(abs(state.get('avg_win', 0) / state.get('avg_loss', 1)) if state.get('avg_loss', 0) != 0 else 0, 2),
        "total_pnl": round(state.get('total_pnl', 0), 2),
        "fees_paid": round(state.get('total_fees', 0), 2)
    }

    services = {
        "oracle_bot": get_service_status("oracle-bot"),
        "data_puller": get_service_status("oracle-data-puller"),
        "autohealer": get_service_status("oracle-autohealer")
    }

    return jsonify({
        "balance": round(state.get('balance', 1000), 2),
        "positions": positions,
        "metrics": metrics,
        "services": services,
        "wins": wins,
        "losses": losses,
        "mode": mode_data.get("mode", "paper"),
        "last_update": datetime.now().isoformat()
    })

@app.route('/api/trades')
def api_trades():
    state = load_state()
    trades = state.get('trades', [])
    formatted = []
    for t in trades:
        formatted.append({
            "timestamp": t.get('exit_time', t.get('entry_time', '')),
            "symbol": t.get('symbol', ''),
            "exchange": t.get('exchange', ''),
            "side": t.get('direction', 'LONG'),
            "entry_price": t.get('entry_price', 0),
            "exit_price": t.get('exit_price', 0),
            "pnl": t.get('net_pnl', t.get('gross_pnl', 0)),
            "size_usd": t.get('size_usd', 0),
            "exit_reason": t.get('exit_reason', ''),
            "entry_time": t.get('entry_time', ''),
            "exit_time": t.get('exit_time', ''),
            "duration_mins": t.get('hold_duration_mins', 0)
        })
    return jsonify(sorted(formatted, key=lambda x: x.get('timestamp', ''), reverse=True))

@app.route('/api/pnl-history')
def api_pnl_history():
    state = load_state()
    trades = state.get('trades', [])
    if not trades:
        return jsonify([])

    sorted_trades = sorted(trades, key=lambda x: x.get('exit_time', x.get('entry_time', '')))
    cumulative = 0
    pnl_history = []
    for trade in sorted_trades:
        pnl = trade.get('net_pnl', trade.get('gross_pnl', 0))
        cumulative += pnl
        pnl_history.append({
            "timestamp": trade.get('exit_time', trade.get('entry_time', '')),
            "pnl": round(cumulative, 2),
            "trade_pnl": round(pnl, 2)
        })
    return jsonify(pnl_history)

@app.route('/api/health')
def api_health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
