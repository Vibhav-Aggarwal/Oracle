# Oracle Bot V2 - Setup Guide

## System Requirements

### Hardware
- **CPU**: 2+ cores recommended
- **RAM**: 2GB minimum, 4GB recommended
- **Storage**: 1GB free space
- **Network**: Stable internet connection

### Software
- Python 3.8 or higher
- pip (Python package manager)
- Git

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/Vibhav-Aggarwal/Oracle.git
cd Oracle
```

### 2. Create Virtual Environment

```bash
# Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy template
cp config/config.example.env .env

# Edit with your settings
nano .env  # or use your preferred editor
```

### 5. Initialize State File

```bash
cp config/oracle_state.template.json oracle_state.json
```

### 6. Configure Exchange API Keys

#### Delta Exchange
1. Go to https://www.delta.exchange
2. Navigate to API Management
3. Create new API key with trading permissions
4. Add to `.env`:
   ```
   DELTA_API_KEY=your_key
   DELTA_API_SECRET=your_secret
   ```

#### Zebpay
1. Go to https://www.zebpay.com
2. Navigate to Settings > API
3. Create new API key
4. Add to `.env`:
   ```
   ZEBPAY_API_KEY=your_key
   ZEBPAY_API_SECRET=your_secret
   ```

#### Coinbase
1. Go to https://www.coinbase.com/settings/api
2. Create new API key with trading permissions
3. Add to `.env`:
   ```
   COINBASE_API_KEY=your_key
   COINBASE_API_SECRET=your_secret
   COINBASE_PASSPHRASE=your_passphrase
   ```

## Running the Bot

### Paper Trading (Recommended First)

```bash
# Ensure TRADING_MODE=PAPER in .env
python src/oracle_bot.py
```

### Starting the Dashboard

```bash
# In a separate terminal
cd dashboard
python app.py
```

Access at: http://localhost:5000

### Running as a Service (Linux)

Create systemd service:

```bash
sudo nano /etc/systemd/system/oracle-bot.service
```

```ini
[Unit]
Description=Oracle Trading Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/Oracle
ExecStart=/path/to/Oracle/venv/bin/python src/oracle_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable oracle-bot
sudo systemctl start oracle-bot
```

## Verification

### Check Bot Status

```bash
# View logs
tail -f /tmp/oracle_bot.log

# Check systemd status (if using service)
sudo systemctl status oracle-bot
```

### Dashboard Health Check

```bash
curl http://localhost:5000/api/status
```

## Troubleshooting

### Bot Won't Start
1. Check Python version: `python --version`
2. Verify dependencies: `pip list`
3. Check logs: `tail -50 /tmp/oracle_bot.log`

### API Connection Errors
1. Verify API keys in `.env`
2. Check internet connectivity
3. Verify exchange status

### WebSocket Disconnects
- The bot auto-reconnects
- Check `oracle_autohealer.py` logs

## Security Best Practices

1. **Never share API keys**
2. **Use read-only keys when possible**
3. **Enable 2FA on exchanges**
4. **Keep `.env` file secure** (chmod 600)
5. **Regular backups of state file**

## Next Steps

1. Run in paper mode for at least 1 week
2. Monitor performance via dashboard
3. Adjust parameters based on results
4. Switch to live only after validation
