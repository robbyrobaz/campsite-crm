# Blofin ML Trading Pipeline Dashboard v2.0

**Professional dark-themed dashboard** for monitoring the Blofin ML trading pipeline in real-time.

## 🚀 Quick Access

**Dashboard URL:** http://localhost:8888/blofin-dashboard.html

![Version](https://img.shields.io/badge/version-2.0.0-blue) ![Status](https://img.shields.io/badge/status-active-success)

## ✨ What's New in v2.0

- 🎨 **Complete visual redesign** with dark modern theme
- 📊 **Advanced trading metrics**: Profit Factor, Sortino Ratio, Max Drawdown
- 📈 **Interactive performance charts** with Chart.js
- 💎 **Professional UI** with gradients, shadows, and animations
- 🔄 **Auto-refresh** every 10 seconds with smooth transitions

## 📊 Features

### Real-Time Monitoring

**Key Metrics Dashboard**
- Pipeline status with live service monitoring
- Hourly trade volume and strategy scores
- Portfolio health score (0-100)
- Win rate and performance indicators

**Advanced Trading Metrics**
- **Profit Factor** - Ratio of total wins to total losses (Current: 0.78)
- **Sortino Ratio** - Downside risk-adjusted returns (Current: -0.16)
- **Sharpe Ratio** - Overall risk-adjusted returns (Avg: -1.03, Max: 914.0)
- **Max Drawdown** - Worst peak-to-trough decline (Current: 1,130%)
- **Expectancy** - Average profit per trade (Current: -0.129%)
- **Win/Loss Ratio** - Average win vs average loss (Current: 1.23)
- **Total PnL** - Cumulative performance across all trades
- **Win Rate** - Percentage of profitable trades (Current: 38.81%)

**Top Strategies**
- Ranked by performance score
- Win rates, Sharpe ratios, PnL percentages
- Signal counts and trade statistics
- Visual indicators for profitability

**ML Model Performance**
- Model accuracy, precision, recall, F1 scores
- Training status indicators
- Performance badges (color-coded)
- Models in development tracking

**Performance Trends**
- 7-day historical chart
- Dual-axis visualization (Score + Win Rate)
- Interactive tooltips and legends
- Gradient fills and smooth curves

## 🛠️ Technical Details

### Server
- **Port:** 8888
- **Framework:** Flask + Flask-CORS
- **Database:** SQLite (`/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db`)

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/health` | Health check and database status |
| `/api/status` | Pipeline status and service heartbeats |
| `/api/strategies` | Top strategies with performance metrics |
| `/api/models` | ML model accuracy and performance |
| `/api/reports` | Latest daily reports and trends |

### Systemd Service

The dashboard runs as a systemd user service and auto-starts on boot.

**Service name:** `blofin-dashboard.service`

**Common commands:**
```bash
# Check status
systemctl --user status blofin-dashboard.service

# Restart
systemctl --user restart blofin-dashboard.service

# View logs
journalctl --user -u blofin-dashboard.service -f

# Stop
systemctl --user stop blofin-dashboard.service

# Disable auto-start
systemctl --user disable blofin-dashboard.service
```

## 📁 Files

```
blofin-dashboard/
├── server.py              # Flask API server
├── blofin-dashboard.html  # Frontend dashboard
└── README.md             # This file
```

## 🔧 Manual Testing

Test individual API endpoints:

```bash
# Health check
curl http://localhost:8888/health | python3 -m json.tool

# Pipeline status
curl http://localhost:8888/api/status | python3 -m json.tool

# Strategies
curl http://localhost:8888/api/strategies | python3 -m json.tool

# Models
curl http://localhost:8888/api/models | python3 -m json.tool

# Reports
curl http://localhost:8888/api/reports | python3 -m json.tool
```

## 🐛 Troubleshooting

### Dashboard won't load
1. Check if service is running: `systemctl --user status blofin-dashboard.service`
2. Check logs: `journalctl --user -u blofin-dashboard.service -n 50`
3. Verify port 8888 is not in use: `lsof -i :8888`

### Empty data on dashboard
1. Verify the database exists: `ls -lh /home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db`
2. Check if pipeline services are running: View "Pipeline Status" card on dashboard
3. Ensure data is being ingested: Check `/api/status` for recent activity

### Hard refresh browser cache
If you see old/stale dashboard content:
- Chrome/Firefox: `Ctrl + Shift + R`
- Or open in incognito/private window

## 📝 Notes

- The dashboard serves live data from the Blofin trading pipeline
- Strategy scores are calculated from the last 24 hours
- Models showing "in training" have not completed testing yet
- Service auto-restarts on crash (RestartSec=2)
- Database is accessed read-only with 10-second timeout

## 🎯 What's Next

Future enhancements:
- Historical charts/graphs for performance trends
- Configurable alerts for strategy performance
- WebSocket support for real-time updates (currently polls every 10s)
- Export reports to CSV/PDF
- Dark mode toggle
