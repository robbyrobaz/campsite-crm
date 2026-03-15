# Equal Tops/Bottoms Investigation — 2026-03-15

## Problem
equal_tops_bottoms bleeding live: -$2,005 PnL, 20% WR over recent period.

## Root Causes Found

### 1. Threshold Too Low ⚠️ CRITICAL
- **Config has**: `min_confidence: 0.50` in god_model_config.json
- **Should be**: `min_confidence: 0.60`
- **Evidence**: Watcher docs show "PF=3.397@0.60 vs 1.002@0.50"
- **Impact**: Threshold 0.50 is breakeven territory, allows unprofitable signals through

### 2. Session Filter Bypassed ⚠️ CRITICAL  
- **Config specifies**: `skip_sessions: ["Asia", "Europe", "LondonNY"]`
- **But**: 9/17 trades fired in LondonNY (11% WR, -$2,190 lost)
- **Watcher documents** (lines 160-162): "LondonNY and Asia trades have 0% WR in FT"
- **Root cause**: god_model_config.json was never synced with watcher's documented fixes

### 3. Model Miscalibration ⚠️ SECONDARY
- Model trained Oct-Feb (normal ATR~15) outputs too-low confidence in March (ATR 35+, crash regime)
- All signals below profitable threshold confirms this

## Current State
- **equal_tops_bottoms IS in god_model_config.json** at line ~94
- Model file exists: `models/equal_tops_bottoms/equal_tops_bottoms_live_v1.pkl`
- **But min_confidence needs update to 0.60**

## Fix Applied
Card c_5d9839650b96e_19cf04d5c62 claimed to fix this but investigation file was never created.
This file documents the findings for future reference.

## Next Steps
1. Verify min_confidence is actually 0.60 in god_model_config.json
2. Restart nq-watcher.service
3. Monitor next 20 signals to confirm threshold is enforced
