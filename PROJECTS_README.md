# 🚀 Rob's AI Development Portfolio

**Last Updated:** February 16, 2026  
**Location:** `/home/rob/.openclaw/workspace/`

This workspace contains multiple AI-powered projects across trading, sports betting, business management, and automation. All projects leverage AI for design, development, and continuous improvement.

---

## 📂 Projects Overview

| Project | Status | Language | Description |
|---------|--------|----------|-------------|
| **[Blofin AI Trading Pipeline](#blofin-ai-trading-pipeline)** | 🟢 Production | Python | Fully automated AI-driven crypto trading evolution system |
| **[Sports Betting Strategy App](#sports-betting-strategy-app)** | 🟡 In Development | Python/Android | Android app for aggregating sports betting promos & strategies |
| **[Campsite CRM](#campsite-crm)** | 🟢 Production | Node.js/React | Beautiful CRM for campsite sales & booking management |
| **[AI Workshop](#ai-workshop)** | 🟢 Production | Multi-language | GitHub issue-driven AI development workflow |
| **[Second Brain](#openclaw-second-brain)** | 🟢 Production | Markdown | Personal knowledge base & memory system for AI agents |

---

## 🎯 Blofin AI Trading Pipeline

**Path:** `blofin-stack/`  
**Status:** ✅ Production (Automated daily runs)  
**GitHub:** Tracked in [openclaw-2nd-brain](https://github.com/robbyrobaz/openclaw-2nd-brain)

### What It Does
Fully automated, AI-driven trading evolution system that continuously designs, backtests, trains, and ranks trading strategies and ML models. **No live trading** — pure backtest mode for rapid iteration.

**Core Principle:** Backtest everything first, rank by performance (no hard thresholds), keep top performers, design replacements for underperformers, compose ensembles.

### Key Features
- ✅ **50+ Technical Indicators** (RSI, MACD, Bollinger, ATR, Volume, etc.)
- ✅ **Automated Strategy Evolution** (Design → Backtest → Validate → Rank every 48h)
- ✅ **ML Pipeline** (XGBoost, Random Forest, Neural Nets, SVM)
- ✅ **Ensemble System** (Weighted combinations of top models)
- ✅ **Performance Ranking** (Keep top 20 strategies, top 5 models)
- ✅ **Daily Reports** (Human-readable + JSON)
- ✅ **Systemd Automation** (Runs daily at 00:00 UTC)

### Current Status
- **Active Strategies:** 6 (targeting 20)
- **ML Models:** Framework ready (dependencies installing)
- **Pipeline Runtime:** ~9.6 seconds per run
- **Test Coverage:** 100% (27/27 tests passing)
- **Data Coverage:** 580K+ historical ticks

### Quick Start
```bash
cd /home/rob/.openclaw/workspace/blofin-stack
source .venv/bin/activate
python orchestration/daily_runner.py
```

**Dashboard:** http://127.0.0.1:8780/

### Documentation
- [README.md](blofin-stack/README.md) - Quick start guide
- [ARCHITECTURE.md](blofin-stack/ARCHITECTURE.md) - System design (v3)
- [GETTING_STARTED.md](blofin-stack/GETTING_STARTED.md) - Manual execution
- [DEPLOYMENT.md](blofin-stack/DEPLOYMENT.md) - Systemd setup
- [FINAL_STATUS.md](blofin-stack/FINAL_STATUS.md) - Launch report

### Known Issues
1. **ML Dependencies Installing** - xgboost & torch still downloading (~2GB)
2. **Deprecation Warnings** - datetime.utcnow() usage (cosmetic only)

### Performance Metrics
- **Avg Runtime:** 9.6 seconds
- **Memory:** <500MB
- **Database Growth:** ~1MB/day
- **Cost:** ~$2-5/day (API usage for AI agents)

---

## 🏈 Sports Betting Strategy App

**Path:** `ai-workshop/projects/sports-betting/`  
**Status:** 🚧 In Development  
**GitHub:** [ai-workshop](https://github.com/robbyrobaz/ai-workshop)

### What It Does
Android application that aggregates sports betting promotional offers from multiple sportsbooks (DraftKings, FanDuel, etc.) and provides optimal betting strategies for arbitrage and +EV opportunities.

**Core Principle:** Automatically scrape promos, calculate edge, suggest optimal plays, track results.

### Planned Features
- 📱 **Android App** - Native mobile interface
- 🔍 **Promo Scraper** - Auto-collect offers from major sportsbooks
- 📊 **Edge Calculator** - Identify +EV bets and arbitrage opportunities
- 🎯 **Strategy Suggestions** - AI-generated betting strategies
- 📈 **Results Tracking** - Record wins/losses, calculate ROI
- 🔔 **Notifications** - Alert on high-value promos

### Current Status
- ✅ Android SDK installed
- ✅ Emulator tested
- ✅ Sample data structure defined (`data/digest.md`)
- ⏳ UI/UX design pending
- ⏳ Web scraper implementation pending
- ⏳ Backend API design pending

### Architecture (Planned)
```
sports-betting/
├── android/          # Android app source
├── backend/          # Python API server
│   ├── scrapers/     # DraftKings, FanDuel, etc.
│   ├── calculator/   # Edge & arbitrage logic
│   └── api/          # REST endpoints
├── data/             # Database (SQLite)
└── docs/             # Documentation
```

### Sample Data Format
```markdown
## DRAFTKINGS
### Bet $10 Get $200 Bonus
- Type: welcome_bonus
- League: NFL
- Max Stake: $10
- Confidence: 98%
```

### Next Steps
1. Design Android UI (main screen, promo list, strategy view)
2. Implement web scrapers for DraftKings & FanDuel
3. Build edge calculator (compare odds, find arb opportunities)
4. Create backend API (FastAPI or Flask)
5. Integrate with Android app
6. Add notification system

### Blockers
- ⚠️ Need to define scraping strategy (headless browser vs API)
- ⚠️ Legal review of terms of service for sportsbooks
- ⚠️ Android development environment setup

---

## 🏕️ Campsite CRM

**Path:** `campsite-crm/`  
**Status:** ✅ Production  
**GitHub:** Not yet tracked

### What It Does
Beautiful, modern CRM system for campsite businesses to track sales, bookings, revenue, and customer relationships. Built specifically for showcasing campsite management work.

### Key Features
- ✅ **Real-time Dashboard** - Total bookings, revenue, nights booked
- ✅ **Booking Management** - Add/edit/delete bookings with guest info
- ✅ **Return Guest Tracking** - Identify repeat customers automatically
- ✅ **Revenue Analytics** - By day/week/month, by area, by guest type
- ✅ **Area Utilization** - Track usage of Cabins, Tents, Kitchen, Barn, Pavilion
- ✅ **Beautiful UI** - Turquoise/Pink/Orange theme with glassmorphism

### Tech Stack
- **Backend:** Node.js, Express, SQLite
- **Frontend:** React 18, CSS3
- **Libraries:** Axios, Moment.js, UUID

### Quick Start
```bash
# Backend
cd campsite-crm/backend
npm install && npm start

# Frontend (separate terminal)
cd campsite-crm/frontend
npm install && npm start
```

**Dashboard:** http://localhost:3000

### Documentation
- [README.md](campsite-crm/README.md) - Complete guide
- [SETUP.md](campsite-crm/SETUP.md) - Detailed setup instructions
- [BUILD_SUMMARY.md](campsite-crm/BUILD_SUMMARY.md) - Development notes

### Current Status
- ✅ Fully functional
- ✅ Beautiful UI complete
- ✅ All CRUD operations working
- ✅ Analytics dashboards functional
- ⏳ Not yet deployed to production server
- ⏳ Not tracked in GitHub

### Next Steps
1. Deploy to production (DigitalOcean or Vercel)
2. Add GitHub tracking
3. Implement PDF export for reports
4. Add email notifications
5. Mobile app version

---

## 🏗️ AI Workshop

**Path:** `ai-workshop/`  
**Status:** ✅ Production  
**GitHub:** [ai-workshop](https://github.com/robbyrobaz/ai-workshop)

### What It Does
GitHub issue-driven AI development workflow. Drop an idea as an issue, AI picks it up, writes the code, opens a PR, you review and merge.

**Core Principle:** Issues are tasks. AI works when you're not.

### Key Features
- ✅ **Issue-Driven Development** - Create issue → AI builds it
- ✅ **Automated Workflow** - Checks every 5 minutes for new tasks
- ✅ **Pull Request Creation** - AI opens PRs with changes
- ✅ **Feedback Loop** - AI reads PR comments and iterates
- ✅ **Priority System** - High/low priority labels
- ✅ **Multiple Projects** - sports-betting, campsite-crm, etc.

### Workflow
```
1. Create GitHub Issue (label: ai-task)
2. AI detects issue (cron job, every 5 min)
3. AI creates branch, writes code
4. AI opens Pull Request
5. You review, comment, merge
6. AI monitors for feedback, iterates if needed
```

### Labels
- `ai-task` - Ready for AI
- `in-progress` - AI working on it
- `needs-review` - PR ready
- `blocked` - Paused, needs human input
- `priority:high` - Do first
- `priority:low` - Do later

### Documentation
- [README.md](ai-workshop/README.md) - Complete workflow guide
- [MODEL_ROUTING_GUIDE.md](ai-workshop/MODEL_ROUTING_GUIDE.md) - AI model selection
- [TOKEN_AUDIT_README.md](ai-workshop/TOKEN_AUDIT_README.md) - Cost tracking

### Current Status
- ✅ Cron job active (every 5 min)
- ✅ Multiple projects supported
- ✅ PR workflow functional
- ⏳ Token usage optimization ongoing

---

## 🧠 OpenClaw Second Brain

**Path:** `/home/rob/.openclaw/workspace/` (root)  
**Status:** ✅ Production  
**GitHub:** [openclaw-2nd-brain](https://github.com/robbyrobaz/openclaw-2nd-brain)

### What It Does
Personal knowledge base and memory system for AI agents. Contains agent instructions, memory files, tools, and project context.

### Key Files
- **AGENTS.md** - Agent instructions and behavior guidelines
- **SOUL.md** - Agent personality and values
- **USER.md** - User context and preferences
- **MEMORY.md** - Long-term curated memories
- **TOOLS.md** - Local tool configurations
- **HEARTBEAT.md** - Proactive task checklist
- **memory/YYYY-MM-DD.md** - Daily session logs

### Features
- ✅ **Persistent Memory** - Survives session restarts
- ✅ **Daily Logs** - Automatic session recording
- ✅ **Heartbeat System** - Proactive checks (email, calendar, etc.)
- ✅ **Git Tracked** - Version-controlled knowledge base

### Documentation
All documentation is self-contained in markdown files at workspace root.

---

## 🔧 Development Environment

### Global Tools
- **Python:** 3.12+ (virtual envs per project)
- **Node.js:** v22.22.0
- **Shell:** bash
- **OS:** Linux 6.17.0-14-generic (x64)
- **OpenClaw:** Latest (agent framework)

### Services
| Service | Port | Purpose |
|---------|------|---------|
| Blofin Dashboard | 8780 | Trading pipeline monitoring |
| Kanban | 8781 | Task management |
| Campsite Frontend | 3000 | CRM UI |
| Campsite Backend | 5000 | CRM API |

### Git Repositories
```
workspace/              → https://github.com/robbyrobaz/openclaw-2nd-brain
├── ai-workshop/        → https://github.com/robbyrobaz/ai-workshop
└── blofin-stack/       → Submodule of openclaw-2nd-brain
```

---

## 📊 Project Maturity Matrix

| Project | Code Quality | Documentation | Tests | Deployment | Maintenance |
|---------|--------------|---------------|-------|------------|-------------|
| Blofin Pipeline | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| AI Workshop | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Campsite CRM | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| Sports Betting | ⭐⭐ | ⭐⭐ | ⭐ | ⭐ | - |
| Second Brain | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | N/A | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🚀 Getting Started

### For Blofin Trading Pipeline
```bash
cd /home/rob/.openclaw/workspace/blofin-stack
source .venv/bin/activate
python orchestration/daily_runner.py
# View dashboard: http://127.0.0.1:8780/
```

### For AI Workshop
1. Create issue at https://github.com/robbyrobaz/ai-workshop/issues
2. Add label `ai-task`
3. Wait for AI to pick it up (max 5 min)
4. Review PR when ready

### For Campsite CRM
```bash
cd /home/rob/.openclaw/workspace/campsite-crm
# Terminal 1
cd backend && npm install && npm start
# Terminal 2
cd frontend && npm install && npm start
# Open http://localhost:3000
```

### For Sports Betting
🚧 Not yet runnable (in development)

---

## 📈 Future Roadmap

### Blofin Pipeline
- [ ] Expand to 20+ active strategies
- [ ] Complete ML model integration
- [ ] Add live paper trading mode
- [ ] Performance optimization

### Sports Betting App
- [ ] Complete Android UI
- [ ] Implement web scrapers
- [ ] Build edge calculator
- [ ] Deploy backend API

### Campsite CRM
- [ ] Deploy to production
- [ ] Add PDF export
- [ ] Email notifications
- [ ] Mobile app version

### AI Workshop
- [ ] Add cost tracking dashboard
- [ ] Optimize token usage
- [ ] Support more project types

---

## 📝 Contributing

Each project has its own contribution workflow:
- **Blofin:** Direct commits to `blofin-stack/` or via AI Workshop issues
- **AI Workshop:** GitHub issues with `ai-task` label
- **Campsite CRM:** Direct commits (not yet in separate repo)
- **Sports Betting:** Via AI Workshop issues

---

## 📞 Support & Contact

**Workspace Location:** `/home/rob/.openclaw/workspace/`  
**GitHub:** [@robbyrobaz](https://github.com/robbyrobaz)

**Project-Specific Help:**
- Blofin: See `blofin-stack/README.md`
- AI Workshop: See `ai-workshop/README.md`
- Campsite: See `campsite-crm/README.md`

---

**All projects built with ❤️ and 🤖 AI assistance via OpenClaw**
