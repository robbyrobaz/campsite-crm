#!/usr/bin/env python3
"""
Position Monitor
Checks open paper trading positions for stop loss / take profit
Updates P&L and logs exits
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# Paths
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'

POSITIONS_LOG = LOGS_DIR / 'open_positions.jsonl'
PAPER_TRADES_LOG = LOGS_DIR / 'paper_trades.jsonl'
EXITS_LOG = LOGS_DIR / 'exits.jsonl'

# API
DEX_TOKEN_API = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Exit parameters
STOP_LOSS_PCT = -30
TAKE_PROFIT_LEVELS = [50, 100, 200, 500, 1000]  # Scale out 20% at each
SCALE_OUT_PCT = 20  # Sell 20% at each level


def get_current_price(contract: str) -> Optional[float]:
    """Get current price from Dexscreener"""
    try:
        url = DEX_TOKEN_API.format(address=contract)
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs', [])
            if pairs:
                return float(pairs[0].get('priceUsd', 0))
        
        return None
    
    except Exception as e:
        return None


def load_open_positions() -> list:
    """Load open positions"""
    if not POSITIONS_LOG.exists():
        return []
    
    positions = []
    
    # Read all position entries (newer entries update older ones)
    all_entries = {}
    with POSITIONS_LOG.open('r') as f:
        for line in f:
            if not line.strip():
                continue
            
            pos = json.loads(line)
            contract = pos['contract']
            
            # Keep latest entry for each contract
            all_entries[contract] = pos
    
    # Filter to only OPEN positions
    for pos in all_entries.values():
        if pos['status'] == 'OPEN':
            positions.append(pos)
    
    return positions


def update_position(position: Dict, current_price: float) -> Dict:
    """Update position with current price and P&L"""
    
    entry_price = position['entry_price_usd']
    position_size = position['position_size_usd']
    
    # Calculate P&L
    if entry_price > 0:
        pnl_pct = ((current_price / entry_price) - 1) * 100
        pnl_usd = position_size * (pnl_pct / 100)
    else:
        pnl_pct = 0
        pnl_usd = 0
    
    position['current_price_usd'] = current_price
    position['pnl_pct'] = pnl_pct
    position['pnl_usd'] = pnl_usd
    position['last_checked'] = datetime.now(timezone.utc).isoformat()
    
    return position


def check_stop_loss(position: Dict) -> Optional[str]:
    """Check if stop loss hit"""
    pnl_pct = position.get('pnl_pct', 0)
    
    if pnl_pct <= STOP_LOSS_PCT:
        return f"STOP_LOSS ({pnl_pct:.1f}%)"
    
    return None


def check_take_profit(position: Dict) -> Optional[tuple]:
    """Check if take profit level hit"""
    pnl_pct = position.get('pnl_pct', 0)
    exits_done = position.get('take_profit_exits', [])
    
    for level in TAKE_PROFIT_LEVELS:
        # Skip if already exited at this level
        if level in exits_done:
            continue
        
        # Check if hit
        if pnl_pct >= level:
            return (level, SCALE_OUT_PCT)
    
    return None


def exit_position(position: Dict, reason: str, exit_pct: float = 100) -> Dict:
    """Exit a position (partial or full)"""
    
    exit_size = position['position_size_usd'] * (exit_pct / 100)
    remaining_size = position['position_size_usd'] - exit_size
    
    exit_entry = {
        'contract': position['contract'],
        'symbol': position['symbol'],
        'entry_price': position['entry_price_usd'],
        'exit_price': position.get('current_price_usd'),
        'position_size': exit_size,
        'pnl_pct': position.get('pnl_pct', 0),
        'pnl_usd': exit_size * (position.get('pnl_pct', 0) / 100),
        'reason': reason,
        'exit_pct': exit_pct,
        'exit_timestamp': datetime.now(timezone.utc).isoformat(),
        'entry_timestamp': position['entry_timestamp'],
        'tier': position['tier'],
        'score': position['score'],
    }
    
    # Log exit
    with EXITS_LOG.open('a') as f:
        f.write(json.dumps(exit_entry) + '\n')
    
    # Update position
    if exit_pct >= 100:
        # Full exit
        position['status'] = 'CLOSED'
        position['close_reason'] = reason
    else:
        # Partial exit
        position['position_size_usd'] = remaining_size
        
        # Track take profit exits
        if 'TAKE_PROFIT' in reason:
            exits = position.get('take_profit_exits', [])
            level = int(reason.split('(')[1].split('%')[0].replace('+', ''))
            exits.append(level)
            position['take_profit_exits'] = exits
    
    # Update in positions log
    with POSITIONS_LOG.open('a') as f:
        f.write(json.dumps(position) + '\n')
    
    return exit_entry


def monitor_cycle():
    """One monitoring cycle"""
    
    print(f"\n{'='*60}")
    print(f"💼 POSITION MONITOR - {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    print(f"{'='*60}")
    
    # Load open positions
    positions = load_open_positions()
    
    if not positions:
        print("No open positions")
        return
    
    print(f"📊 Monitoring {len(positions)} open positions...\n")
    
    exits_this_cycle = 0
    
    for pos in positions:
        contract = pos['contract']
        symbol = pos['symbol']
        
        # Get current price
        current_price = get_current_price(contract)
        
        if not current_price:
            print(f"⚠️  {symbol}: No price data")
            continue
        
        # Update position
        pos = update_position(pos, current_price)
        
        # Check stop loss
        stop_reason = check_stop_loss(pos)
        if stop_reason:
            print(f"🛑 {symbol}: {stop_reason} - EXITING 100%")
            exit_position(pos, stop_reason, 100)
            exits_this_cycle += 1
            continue
        
        # Check take profit
        tp_check = check_take_profit(pos)
        if tp_check:
            level, pct = tp_check
            reason = f"TAKE_PROFIT (+{level}%)"
            print(f"💰 {symbol}: {reason} - EXITING {pct}%")
            exit_position(pos, reason, pct)
            exits_this_cycle += 1
            
            # Continue checking (might still be open with remaining size)
            if pos['status'] == 'OPEN':
                print(f"   Remaining: {pos['position_size_usd']:.2f} USD")
            
            continue
        
        # Just update (no exit)
        print(f"📈 {symbol}: {pos['pnl_pct']:+.1f}% (${pos['pnl_usd']:+.2f})")
        
        # Log updated position
        with POSITIONS_LOG.open('a') as f:
            f.write(json.dumps(pos) + '\n')
    
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY: {exits_this_cycle} exits this cycle")
    print(f"{'='*60}")


def main():
    """Main loop"""
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║             💼 POSITION MONITOR 💼                           ║
║                                                              ║
║   Monitors open positions for stop loss / take profit       ║
║   Stop Loss: -30%                                            ║
║   Take Profit: +50%, +100%, +200%, +500%, +1000%            ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    print(f"📁 Logs: {LOGS_DIR}")
    print(f"🔄 Checking every 2 minutes...\n")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            
            try:
                monitor_cycle()
            except Exception as e:
                print(f"\n❌ Error in monitoring cycle: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"\n⏳ Waiting 2 minutes... (Cycle #{cycle_count})")
            time.sleep(120)  # 2 minutes
    
    except KeyboardInterrupt:
        print(f"\n\n🛑 Monitor stopped. Total cycles: {cycle_count}")


if __name__ == '__main__':
    main()
