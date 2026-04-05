#!/usr/bin/env python3
"""
Multi-Source Memecoin Scanner + Paper Trader
Combines: Pump.fun + Dexscreener + Telegram
Goal: Find 5% winners, let them run, cut 50% rugs fast
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Paths
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SEEN_FILE = BASE_DIR / 'seen_contracts.txt'
PUMPFUN_LOG = LOGS_DIR / 'pumpfun_tokens.jsonl'
SCORED_LOG = LOGS_DIR / 'scored_tokens.jsonl'
PAPER_TRADES_LOG = LOGS_DIR / 'paper_trades.jsonl'
POSITIONS_LOG = LOGS_DIR / 'open_positions.jsonl'

# Telegram signals from other scanner
TELEGRAM_DIR = Path.home() / '.openclaw/workspace/autonomous-memecoin-hunter/logs'
TELEGRAM_SIGNALS = TELEGRAM_DIR / 'signals.jsonl'

# APIs
PUMPFUN_API = "https://frontend-api-v3.pump.fun/coins"
DEX_TOKEN_API = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Filters
MIN_LIQUIDITY_USD = 500
MIN_SCORE_TO_ENTER = 60  # Tier 2+ only

# Paper trading
STARTING_BALANCE = 100.0
POSITION_SIZE_BASE = 5.0
current_balance = STARTING_BALANCE

# Headers for pump.fun
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://pump.fun/',
}


def load_seen() -> set:
    """Load seen contracts"""
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().strip().split('\n'))


def mark_seen(contract: str):
    """Mark contract as seen"""
    with SEEN_FILE.open('a') as f:
        f.write(f"{contract}\n")


def load_telegram_contracts() -> Dict[str, dict]:
    """Load contracts mentioned on Telegram"""
    contracts = {}
    
    if not TELEGRAM_SIGNALS.exists():
        return contracts
    
    with TELEGRAM_SIGNALS.open('r') as f:
        for line in f:
            if not line.strip():
                continue
            signal = json.loads(line)
            contract = signal.get('contract')
            if contract:
                if contract not in contracts:
                    contracts[contract] = {
                        'channels': [],
                        'first_seen': signal.get('timestamp')
                    }
                contracts[contract]['channels'].append(signal.get('channel'))
    
    return contracts


def get_new_pumpfun_tokens(limit=50) -> List[Dict]:
    """Fetch latest tokens from pump.fun"""
    try:
        url = f"{PUMPFUN_API}?offset=0&limit={limit}&sort=created_timestamp&order=DESC"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"⚠️  Pump.fun API error: {resp.status_code}")
            return []
    
    except Exception as e:
        print(f"❌ Pump.fun API error: {e}")
        return []


def get_dexscreener_data(contract: str) -> Optional[Dict]:
    """Get Dexscreener data for a token"""
    try:
        url = DEX_TOKEN_API.format(address=contract)
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs', [])
            if pairs:
                return pairs[0]  # Main pair
        
        return None
    
    except Exception as e:
        return None


def calculate_age_minutes(timestamp_ms: int) -> float:
    """Calculate age in minutes"""
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    return (now_ms - timestamp_ms) / 60000


def score_token(pumpfun: Dict, dex: Optional[Dict], telegram: Optional[Dict]) -> Dict:
    """Score a token (0-100 points)"""
    
    score = 0
    details = {}
    
    contract = pumpfun['mint']
    age_min = calculate_age_minutes(pumpfun['created_timestamp'])
    
    # === SPEED SCORE (0-30) ===
    if age_min < 5:
        speed_score = 30
    elif age_min < 15:
        speed_score = 25
    elif age_min < 30:
        speed_score = 20
    elif age_min < 60:
        speed_score = 15
    elif age_min < 120:
        speed_score = 10
    else:
        speed_score = 5
    
    score += speed_score
    details['speed'] = speed_score
    details['age_minutes'] = round(age_min, 1)
    
    # === LIQUIDITY SCORE (0-15) ===
    # Use Dex USD value if available, else pump.fun SOL reserves
    if dex:
        liq_usd = float(dex.get('liquidity', {}).get('usd', 0))
    else:
        # Convert SOL reserves to rough USD (1 SOL ~= $80)
        sol_reserves = pumpfun.get('real_sol_reserves', 0) / 1e9
        liq_usd = sol_reserves * 80
    
    if liq_usd >= 50000:
        liq_score = 15
    elif liq_usd >= 10000:
        liq_score = 12
    elif liq_usd >= 5000:
        liq_score = 10
    elif liq_usd >= 1000:
        liq_score = 7
    elif liq_usd >= 500:
        liq_score = 3
    else:
        liq_score = 0
    
    score += liq_score
    details['liquidity'] = liq_score
    details['liquidity_usd'] = round(liq_usd, 2)
    
    # === ENGAGEMENT SCORE (0-15) ===
    reply_count = pumpfun.get('reply_count', 0)
    
    if dex:
        txns = dex.get('txns', {}).get('h1', {})
        total_txns = txns.get('buys', 0) + txns.get('sells', 0)
    else:
        total_txns = 0
    
    engagement = reply_count + (total_txns / 10)  # Weight txns less
    
    if engagement > 100:
        eng_score = 15
    elif engagement > 50:
        eng_score = 12
    elif engagement > 20:
        eng_score = 10
    elif engagement > 10:
        eng_score = 7
    elif engagement > 5:
        eng_score = 3
    else:
        eng_score = 0
    
    score += eng_score
    details['engagement'] = eng_score
    details['reply_count'] = reply_count
    details['txns_1h'] = total_txns
    
    # === PRICE ACTION SCORE (0-20) ===
    price_score = 0
    price_change_1h = 0
    
    if dex:
        price_change_1h = float(dex.get('priceChange', {}).get('h1', 0))
        
        if price_change_1h > 100:
            price_score = 20
        elif price_change_1h > 50:
            price_score = 15
        elif price_change_1h > 20:
            price_score = 10
        elif price_change_1h > 0:
            price_score = 5
        elif price_change_1h > -20:
            price_score = 2
        else:
            price_score = 0
    
    score += price_score
    details['price_action'] = price_score
    details['price_change_1h'] = round(price_change_1h, 1)
    
    # === BUY PRESSURE SCORE (0-10) ===
    buy_score = 0
    buy_ratio = 0
    
    if dex:
        txns = dex.get('txns', {}).get('h1', {})
        buys = txns.get('buys', 0)
        sells = txns.get('sells', 0)
        
        if sells > 0:
            buy_ratio = buys / sells
            
            if buy_ratio > 3.0:
                buy_score = 10
            elif buy_ratio > 2.0:
                buy_score = 8
            elif buy_ratio > 1.5:
                buy_score = 6
            elif buy_ratio > 1.0:
                buy_score = 4
            elif buy_ratio > 0.5:
                buy_score = 2
    
    score += buy_score
    details['buy_pressure'] = buy_score
    details['buy_ratio'] = round(buy_ratio, 2)
    
    # === MULTI-SOURCE BONUS (0-15) ===
    sources = 1  # Always have pump.fun
    
    if dex and liq_usd >= MIN_LIQUIDITY_USD:
        sources += 1
    
    if telegram:
        sources += 1
        channel_count = len(telegram.get('channels', []))
        
        if channel_count >= 2:
            sources += 0.5  # Bonus for multi-channel
    
    if sources >= 3:
        multi_score = 15
    elif sources >= 2.5:
        multi_score = 12
    elif sources >= 2:
        multi_score = 10
    else:
        multi_score = 0
    
    score += multi_score
    details['multi_source'] = multi_score
    details['sources'] = sources
    
    # === RED FLAGS (SUBTRACT) ===
    flags = []
    
    if pumpfun.get('is_banned'):
        score -= 100
        flags.append('BANNED')
    
    if pumpfun.get('nsfw'):
        score -= 20
        flags.append('NSFW')
    
    # Check if heavily boosted (paid shill)
    if dex:
        boosts = dex.get('boosts', {}).get('active', 0)
        if boosts > 20:
            score -= 10
            flags.append(f'BOOSTED_{boosts}')
    
    # Check if ATH way higher than current (late to party)
    ath_mc = pumpfun.get('ath_market_cap', pumpfun.get('market_cap', 0))
    current_mc = pumpfun.get('market_cap', ath_mc)
    
    if ath_mc > 0 and current_mc > 0:
        ath_ratio = ath_mc / current_mc
        if ath_ratio > 100:
            score -= 15
            flags.append(f'ATH_{int(ath_ratio)}x')
    
    # No social links
    if not pumpfun.get('twitter') and not pumpfun.get('telegram'):
        score -= 10
        flags.append('NO_SOCIALS')
    
    details['red_flags'] = flags
    details['red_flag_penalty'] = sum([
        -100 if 'BANNED' in flags else 0,
        -20 if 'NSFW' in flags else 0,
        -10 if any('BOOSTED' in f for f in flags) else 0,
        -15 if any('ATH' in f for f in flags) else 0,
        -10 if 'NO_SOCIALS' in flags else 0,
    ])
    
    # Final score
    score = max(0, min(100, score))  # Clamp 0-100
    
    return {
        'contract': contract,
        'symbol': pumpfun.get('symbol', 'UNK'),
        'name': pumpfun.get('name', ''),
        'score': round(score, 1),
        'details': details,
        'twitter': pumpfun.get('twitter'),
        'telegram': pumpfun.get('telegram'),
        'website': pumpfun.get('website'),
        'created_timestamp': pumpfun['created_timestamp'],
        'scored_timestamp': datetime.now(timezone.utc).isoformat(),
    }


def determine_tier(score: float) -> tuple:
    """Determine entry tier and position size"""
    if score >= 80:
        return ('TIER_1_MAX', 3.0)  # 3x position
    elif score >= 60:
        return ('TIER_2_HIGH', 2.0)  # 2x position
    elif score >= 40:
        return ('TIER_3_MED', 1.0)  # 1x position
    else:
        return ('TIER_4_LOW', 0.0)  # Skip


def paper_trade_entry(scored: Dict):
    """Enter a paper trade"""
    global current_balance
    
    tier, multiplier = determine_tier(scored['score'])
    
    if multiplier == 0:
        return  # Skip low scores
    
    position_size = POSITION_SIZE_BASE * multiplier
    
    if current_balance < position_size:
        print(f"  ⚠️  Insufficient balance (${current_balance:.2f} < ${position_size:.2f})")
        return
    
    # Enter position
    entry = {
        'contract': scored['contract'],
        'symbol': scored['symbol'],
        'tier': tier,
        'score': scored['score'],
        'entry_price_usd': scored['details'].get('liquidity_usd', 0) / 1000000,  # Rough estimate
        'position_size_usd': position_size,
        'entry_timestamp': datetime.now(timezone.utc).isoformat(),
        'stop_loss_pct': -30,  # -30% stop
        'take_profit_levels': [50, 100, 200, 500, 1000],  # Scale out points
        'status': 'OPEN',
    }
    
    current_balance -= position_size
    
    # Log trade
    with PAPER_TRADES_LOG.open('a') as f:
        f.write(json.dumps(entry) + '\n')
    
    # Add to open positions
    with POSITIONS_LOG.open('a') as f:
        f.write(json.dumps(entry) + '\n')
    
    print(f"  📈 ENTERED {tier}: {scored['symbol']} @ ${position_size:.2f} (Score: {scored['score']}, Balance: ${current_balance:.2f})")


def scan_cycle():
    """One scan cycle"""
    
    print(f"\n{'='*60}")
    print(f"🔍 SCAN CYCLE - {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    print(f"{'='*60}")
    
    # Load seen contracts
    seen = load_seen()
    
    # Load Telegram signals
    telegram_contracts = load_telegram_contracts()
    print(f"📱 Telegram: {len(telegram_contracts)} contracts mentioned")
    
    # Fetch new tokens from pump.fun
    print(f"🔥 Fetching pump.fun tokens...")
    pumpfun_tokens = get_new_pumpfun_tokens(limit=50)
    print(f"  Found {len(pumpfun_tokens)} latest tokens")
    
    new_count = 0
    scored_count = 0
    entered_count = 0
    
    for pf_token in pumpfun_tokens:
        contract = pf_token['mint']
        
        # Skip if seen
        if contract in seen:
            continue
        
        new_count += 1
        mark_seen(contract)
        
        # Log raw pump.fun data
        with PUMPFUN_LOG.open('a') as f:
            f.write(json.dumps({
                'contract': contract,
                'data': pf_token,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }) + '\n')
        
        # Get Dexscreener data (might not exist yet if very new)
        age_min = calculate_age_minutes(pf_token['created_timestamp'])
        
        dex_data = None
        if age_min > 2:  # Only check Dex if >2 min old
            time.sleep(0.5)  # Rate limit
            dex_data = get_dexscreener_data(contract)
        
        # Check Telegram mention
        telegram_data = telegram_contracts.get(contract)
        
        # Score it
        scored = score_token(pf_token, dex_data, telegram_data)
        
        # Log scored token
        with SCORED_LOG.open('a') as f:
            f.write(json.dumps(scored) + '\n')
        
        scored_count += 1
        
        # Print summary
        tier, multiplier = determine_tier(scored['score'])
        emoji = '🔥' if scored['score'] >= 80 else '✅' if scored['score'] >= 60 else '⚠️' if scored['score'] >= 40 else '❌'
        
        print(f"\n{emoji} {scored['symbol']} - Score: {scored['score']:.0f} ({tier})")
        print(f"   Age: {scored['details']['age_minutes']:.0f}m | Liq: ${scored['details']['liquidity_usd']:.0f}")
        print(f"   Engagement: {scored['details']['reply_count']} replies, {scored['details']['txns_1h']} txns")
        if dex_data:
            print(f"   Price: {scored['details']['price_change_1h']:+.0f}% (1h) | Buy ratio: {scored['details']['buy_ratio']:.1f}")
        if telegram_data:
            print(f"   📱 Telegram: {len(telegram_data['channels'])} channels")
        if scored['details']['red_flags']:
            print(f"   🚩 Flags: {', '.join(scored['details']['red_flags'])}")
        
        # Enter paper trade if score high enough
        if scored['score'] >= MIN_SCORE_TO_ENTER:
            paper_trade_entry(scored)
            entered_count += 1
    
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY: {new_count} new | {scored_count} scored | {entered_count} entered")
    print(f"💰 Balance: ${current_balance:.2f}")
    print(f"{'='*60}")


def main():
    """Main loop"""
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║   🚀 MULTI-SOURCE MEMECOIN SCANNER + PAPER TRADER 🚀        ║
║                                                              ║
║   Sources: Pump.fun + Dexscreener + Telegram                ║
║   Strategy: Find 5% winners, cut 50% rugs, LET WINNERS RUN  ║
║   Starting Balance: $100                                     ║
║   Min Score to Enter: 60 (Tier 2+)                          ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    print(f"📁 Logs: {LOGS_DIR}")
    print(f"🔄 Scanning every 60 seconds...\n")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            
            try:
                scan_cycle()
            except Exception as e:
                print(f"\n❌ Error in scan cycle: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"\n⏳ Waiting 60 seconds... (Cycle #{cycle_count})")
            time.sleep(60)
    
    except KeyboardInterrupt:
        print(f"\n\n🛑 Scanner stopped. Final balance: ${current_balance:.2f}")
        print(f"📊 Total cycles: {cycle_count}")


if __name__ == '__main__':
    main()
