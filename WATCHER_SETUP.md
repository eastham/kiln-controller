# Kiln Watcher Setup Guide

The kiln watcher is a continuous monitoring service that tracks your kiln's state and sends Slack notifications for important events.

## Features

- **State Machine Tracking**: Monitors three states - OFFLINE, IDLE, and RUNNING
- **Slack Notifications** for:
  - Kiln starting a run (IDLE → RUNNING)
  - Kiln completing a run (RUNNING → IDLE)
  - **ALERT**: Connection lost during a run (RUNNING → OFFLINE)
  - **ALERT**: Temperature exceeds maximum threshold (default: 1200°F)
  - **ALERT**: Temperature stuck at error value for >60 seconds (default: 32°F ±1°)
- **Graceful Network Failure Handling**: 60-second grace period before considering kiln offline
- **Runs as a systemd service**: Automatic restart on failure, starts on boot

## State Transitions

```
OFFLINE ──────────────> IDLE ──────────────> RUNNING
   ^                      ^                      |
   |                      |                      |
   |                      └──────────────────────┘
   |                                              |
   └──────────────────────────────────────────────┘
                   (ALERT if from RUNNING)
```

- **OFFLINE → IDLE**: Kiln powered on (no notification)
- **IDLE → RUNNING**: Kiln started a run ✉️ Notification
- **RUNNING → IDLE**: Kiln completed successfully ✉️ Notification
- **RUNNING → OFFLINE**: Connection lost during run 🚨 ALERT
- **IDLE → OFFLINE**: Normal power-off (no notification)

## Installation

### 1. Create Slack Webhook

1. Go to https://api.slack.com/apps
2. Create a new app or select existing app
3. Enable "Incoming Webhooks"
4. Create a new webhook for your desired channel
5. Copy the webhook URL (it will look like `https://hooks.slack.com/services/XXX/YYY/ZZZ`)

### 2. Test the Watcher

Run manually to verify it works (replace with your actual webhook URL):

```bash
cd /home/pi/kiln-controller
python3 watcher.py --slack-hook "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

**Optional parameters:**
```bash
python3 watcher.py \
  --slack-hook "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" \
  --kiln-url "http://192.168.1.84:8081" \
  --check-interval 10 \
  --offline-threshold 60 \
  --max-temp 1200 \
  --error-temp 32
```

Run `python3 watcher.py --help` to see all available options.

You should see output like:
```
2025-12-09 10:30:00 INFO: Kiln watcher started - monitoring http://192.168.1.84:8081/api/state
2025-12-09 10:30:00 INFO: Check interval: 10s, Offline threshold: 60s
2025-12-09 10:30:00 INFO: OK - State: IDLE, Temp: 72.5°, Target: 0.0°, Runtime: 0s
```

Press Ctrl+C to stop.

### 3. Install as Systemd Service

**Important**: Edit `kiln-watcher.service` and update the Slack webhook URL:

```ini
Environment="SLACK_HOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

Also adjust these lines if your installation directory is different:
```ini
User=pi                                                    # Your username
WorkingDirectory=/home/pi/kiln-controller                  # Path to kiln-controller
```

Then install and start the service:

```bash
# Copy service file to systemd
sudo cp kiln-watcher.service /etc/systemd/system/

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable kiln-watcher

# Start the service now
sudo systemctl start kiln-watcher

# Check that it's running
sudo systemctl status kiln-watcher
```

### 4. View Logs

```bash
# View recent logs
sudo journalctl -u kiln-watcher -n 50

# Follow logs in real-time
sudo journalctl -u kiln-watcher -f

# View logs for a specific time range
sudo journalctl -u kiln-watcher --since "1 hour ago"
```

## Maintenance

### Restart the Service

```bash
sudo systemctl restart kiln-watcher
```

### Stop the Service

```bash
sudo systemctl stop kiln-watcher
```

### Disable Automatic Start

```bash
sudo systemctl disable kiln-watcher
```

### Update Configuration

To change monitoring parameters (check interval, thresholds, etc.):

1. Edit `kiln-watcher.service` and modify the `ExecStart` line to add parameters:
   ```ini
   ExecStart=/usr/bin/python3 /home/pi/kiln-controller/watcher.py \
     --slack-hook=${SLACK_HOOK_URL} \
     --max-temp 1300 \
     --error-temp 35
   ```
2. Reload systemd and restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart kiln-watcher
   ```

To change the Slack webhook URL:

1. Edit `kiln-watcher.service` and update the `Environment` line
2. Restart the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart kiln-watcher
   ```

## Troubleshooting

### Service Won't Start

Check the logs for errors:
```bash
sudo journalctl -u kiln-watcher -n 100
```

Common issues:
- **Permission denied**: Make sure `watcher.py` is executable and readable by the service user
- **Module not found**: Install required Python packages: `pip3 install requests`
- **Connection refused**: Verify the kiln URL is correct and the kiln-controller is running

### Not Receiving Slack Notifications

1. Test the Slack webhook manually:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test message"}' \
     https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   ```

2. Check watcher logs for Slack API errors:
   ```bash
   sudo journalctl -u kiln-watcher | grep -i slack
   ```

### Watcher Shows Wrong State

The watcher determines state from `/api/state` endpoint. Test it directly:
```bash
curl http://192.168.1.84:8081/api/state | python3 -m json.tool
```

You should see JSON with a `state` field showing "IDLE", "RUNNING", or "PAUSED".

## Running on a Separate Server

To run the watcher on a different machine (not the Raspberry Pi):

1. Copy `watcher.py` to the monitoring server
2. Install Python 3 and requests: `pip3 install requests`
3. Update the `kiln_url` to point to your Pi's IP address
4. Follow the systemd service installation steps above

The watcher only needs network access to the kiln's API endpoint - it doesn't need to run on the Pi itself.

## API Endpoint

The watcher uses the `/api/state` endpoint which was added to `kiln-controller.py`. This endpoint returns:

```json
{
  "state": "IDLE",           // or "RUNNING", "PAUSED"
  "temperature": 72.5,
  "target": 0.0,
  "runtime": 0,
  "totaltime": 0,
  "cost": 0.0,
  "heat": 0.0,
  "heat_rate": 0.0,
  ...
}
```

The watcher specifically checks the `state` field to determine transitions.
