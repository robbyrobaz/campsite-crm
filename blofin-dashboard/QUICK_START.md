# Blofin Dashboard - Quick Start

## 🚀 Access the Dashboard

**Open in your browser:**
```
http://localhost:8888/blofin-dashboard.html
```

**Hard refresh to see latest changes:**
- Chrome/Firefox: `Ctrl + Shift + R`
- Safari: `Cmd + Shift + R`

---

## 📊 What You're Looking At

### Top Row - Key Metrics
- **Pipeline Status** - Is the system running?
- **Trades (1h)** - How many trades in last hour
- **Strategy Scores** - How many evaluations
- **Portfolio Health** - Overall health score (0-100)

### Advanced Metrics Grid
8 professional trading metrics:
- **Profit Factor** - Are we making money? (>1.0 = yes)
- **Sortino Ratio** - Risk-adjusted returns (downside only)
- **Sharpe Ratio** - Classic risk metric
- **Max Drawdown** - Worst loss from peak
- **Expectancy** - Average profit per trade
- **Win/Loss Ratio** - Size of wins vs losses
- **Total PnL** - Overall profit/loss %
- **Total Trades** - Sample size

### Services & Performance
- **Left:** Pipeline services status (running/idle)
- **Right:** Portfolio metrics (score, win rate, active counts)

### Strategies & Models
- **Left:** Top 8 strategies ranked by performance
- **Right:** 5 ML models with accuracy metrics

### Charts
- **Left:** Strategy performance trends (7 days)
- **Right:** Model training accuracy history

---

## 🎨 Color Guide

**Green** = Good (profit, high accuracy, running)  
**Red** = Bad (loss, low accuracy, failing)  
**Orange/Yellow** = Warning (borderline)  
**Cyan/Purple** = Neutral info  

---

## 🔧 Service Management

### Check if dashboard is running
```bash
systemctl --user status blofin-dashboard.service
```

### Restart the dashboard
```bash
systemctl --user restart blofin-dashboard.service
```

### View live logs
```bash
journalctl --user -u blofin-dashboard.service -f
```

### Stop the dashboard
```bash
systemctl --user stop blofin-dashboard.service
```

---

## 📈 Understanding the Metrics

### Is the system profitable?
Look at **Profit Factor**:
- Above 1.0 = Making money ✅
- Below 1.0 = Losing money ❌
- Current: 0.783 (losing)

### Is the win rate good?
Look at **Win Rate**:
- Above 50% = Good
- 40-50% = OK if wins are bigger than losses
- Below 40% = Need much bigger wins
- Current: 38.81% (borderline)

### Are wins bigger than losses?
Look at **Win/Loss Ratio**:
- Above 2.0 = Excellent (wins 2x losses)
- Above 1.5 = Good
- Above 1.0 = Acceptable
- Current: 1.23 (decent)

### How bad can it get?
Look at **Max Drawdown**:
- Below 10% = Excellent risk control
- 10-20% = Good
- 20-50% = Acceptable
- Above 50% = High risk
- Current: 1,130% (extreme - position sizing issue)

---

## 🤖 ML Model Performance

All models show **train accuracy** (test accuracy coming soon):
- direction_predictor: **100%** ✅
- volatility_regressor: **99.11%** ✅
- momentum_classifier: **97.88%** ✅
- risk_scorer: **96.0%** ✅
- price_predictor: **0%** ⏳ (training)

**What this means:**
Models are learning patterns well in training, but we need test accuracy to confirm they generalize to new data.

---

## ⚡ Quick Troubleshooting

### Dashboard won't load
```bash
# Check service
systemctl --user status blofin-dashboard.service

# Check if port is blocked
lsof -i :8888

# Restart it
systemctl --user restart blofin-dashboard.service
```

### Data looks old
- Hard refresh: `Ctrl + Shift + R`
- Wait 10 seconds (auto-refresh cycle)
- Check pipeline services are running (on dashboard)

### Charts not showing
- Hard refresh browser
- Check browser console for errors (F12)
- Verify Chart.js CDN is accessible

---

## 📚 More Documentation

- **FEATURES.md** - Complete feature guide (14KB)
- **CHANGELOG.md** - Version history
- **README.md** - Detailed user guide

---

## 🎯 What to Focus On

**Every morning:**
1. Check **Pipeline Status** (running?)
2. Check **Profit Factor** (making money?)
3. Check **Win Rate** (above 40%?)
4. Review **Top Strategies** (which ones working?)

**Every week:**
1. Review **Performance Trends** chart
2. Check **Max Drawdown** (risk increasing?)
3. Review **ML Models** accuracy
4. Analyze **Sortino/Sharpe** ratios

**Every month:**
1. Export data for detailed analysis
2. Tune strategy parameters
3. Retrain ML models
4. Review position sizing rules

---

**Dashboard updates automatically every 10 seconds. Just leave it open!**
