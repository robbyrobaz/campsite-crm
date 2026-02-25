# Blofin Dashboard - Changelog

## v2.0.0 - Professional Redesign (2026-02-16)

### 🎨 Visual Design Overhaul

**Dark Modern Theme**
- Deep dark background (`#0a0e27`) with gradient overlays
- Card-based layout with hover effects and shadows
- Gradient accent colors (cyan to purple)
- Professional typography with Inter font family
- Smooth animations and transitions

**UI Components**
- Glass-morphism style cards with borders
- Gradient status indicators with pulse animations
- Color-coded metrics (green for positive, red for negative)
- Responsive grid layouts (4-column, 2-column, adaptive)
- Chart.js integration for performance trends
- Badge system for statuses and categories

### 📊 Advanced Trading Metrics

**New Endpoint:** `/api/advanced_metrics`

**Trading Metrics:**
- **Profit Factor:** 0.783 (total wins / total losses)
- **Expectancy:** -0.129% (average profit per trade)
- **Win/Loss Ratio:** 1.23 (average win / average loss)
- **Total PnL:** -2,803% (cumulative performance)
- **Win Rate:** 38.81% (8,452 wins / 21,776 total trades)

**Risk Metrics:**
- **Sortino Ratio:** -0.162 (downside risk-adjusted return)
- **Sharpe Ratio:** -1.032 avg, 914.0 max (risk-adjusted return)
- **Max Drawdown:** 1,130% (worst peak-to-trough decline)
- **Avg Drawdown:** 21.12% (typical decline)

**Strategy Metrics:**
- **Avg Strategy Score:** 18.95
- **Avg Strategy Win Rate:** 39.36%

### 🚀 New Features

1. **Performance Chart**
   - Dual-axis line chart (Score + Win Rate)
   - 7-day historical trends
   - Interactive tooltips
   - Gradient fills under curves

2. **Enhanced Strategy Cards**
   - Ranked display (#1, #2, etc.)
   - Score badges with gradients
   - 4-stat grid per strategy
   - Hover animations

3. **Smart Model Display**
   - Filters out untrained models
   - Shows "Models in Training" state
   - Badge indicators for accuracy tiers
   - Precision, Recall, F1 Score display

4. **Key Metrics Dashboard**
   - 4 highlighted overview cards
   - Large, readable numbers
   - Change indicators with arrows
   - Status color coding

5. **Service Monitor**
   - Service status badges
   - Time-since-last-heartbeat
   - Running/Idle indicators
   - Visual health check

### 🔧 Technical Improvements

**Frontend:**
- Single-page vanilla JavaScript (no build step required)
- Chart.js 4.4.0 for visualizations
- CSS Grid & Flexbox for responsive layouts
- Custom CSS variables for theming
- Auto-refresh every 10 seconds

**Backend:**
- New advanced metrics calculation endpoint
- Complex SQL queries for profit factor, Sortino, drawdown
- Proper handling of closed vs open trades
- 7-day rolling window for strategy metrics
- Error handling with graceful degradation

**Performance:**
- Database queries optimized with indexes
- Connection pooling with 10s timeout
- Minimal JavaScript bundle (no React overhead)
- Efficient DOM updates

### 📐 Design Specifications

**Color Palette:**
```css
Background: #0a0e27 (primary), #151b3d (secondary)
Cards: #1a2142 with #2d3561 borders
Accent: #00d4ff (cyan), #7c3aed (purple)
Success: #10b981, Warning: #f59e0b, Danger: #ef4444
Text: #e5e7eb (primary), #9ca3af (secondary), #6b7280 (muted)
```

**Typography:**
- Headers: 700-800 weight, -1px letter spacing
- Metrics: 1.8-2.5rem font size
- Labels: 0.85rem, uppercase, 0.5px letter spacing

**Spacing:**
- Card padding: 24px
- Grid gaps: 16-20px
- Border radius: 10-16px
- Shadows: 0 8px 16px rgba(0,0,0,0.4)

### 🎯 Metrics Explained

**Profit Factor**
- Ratio of gross profits to gross losses
- > 1.0 = profitable system
- Current: 0.783 (needs improvement)

**Sortino Ratio**
- Like Sharpe but only penalizes downside volatility
- > 1.0 = good, > 2.0 = excellent
- Current: -0.162 (negative returns)

**Expectancy**
- Average amount won/lost per trade
- Positive = profitable system
- Current: -0.129% (slight edge against)

**Win/Loss Ratio**
- Size of average win vs average loss
- > 1.0 = wins bigger than losses
- Current: 1.23 (wins 23% larger)

### 📱 Responsive Design

- Desktop: 4-column grid for metrics
- Tablet: 2-column adaptive
- Mobile: Single column stack
- Breakpoint: 768px

### 🔒 Security & Reliability

- CORS enabled for local development
- 10-second database timeout
- Graceful error handling
- Service auto-restart on crash
- Read-only database access

---

## v1.0.0 - Initial Release (2026-02-16)

- Basic Flask server
- Simple HTML dashboard
- 4 API endpoints
- Systemd integration
- SQLite data source
