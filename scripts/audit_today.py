import json
from collections import Counter
from datetime import datetime

trades = []
decisions = []
logs = []
types = Counter()

with open('journal/2026-10-16.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        item = json.loads(line)
        t = item.get('kind')
        types[t] += 1
        if t == 'trade':
            trades.append(item.get('data'))
        elif t == 'decision':
            decisions.append(item.get('data'))
        elif t == 'log':
            logs.append(item.get('data'))

print(f"Record types: {dict(types)}")
print(f"Total trades today: {len(trades)}")

if trades:
    gross_total = sum(t['gross_pnl'] for t in trades)
    fees_total = sum(t['fees'] for t in trades)
    net_total = sum(t['net_pnl'] for t in trades)
    wins = [t for t in trades if t['net_pnl'] > 0]
    losses = [t for t in trades if t['net_pnl'] <= 0]

    print(f"Gross PnL: ${gross_total:,.2f}")
    print(f"Fees:      ${fees_total:,.2f}")
    print(f"Net PnL:   ${net_total:,.2f}")
    print(f"Win rate:  {len(wins)}/{len(trades)} ({len(wins)/len(trades)*100:.1f}%)")

    reasons = Counter(t['reason'] for t in trades)
    print("Exit reasons:", dict(reasons))

    symbols = Counter(t['symbol'] for t in trades)
    print("Symbols traded:", dict(symbols))

    print("\nTrades detail:")
    eq = 985213.0
    cum_pnl = 0.0
    for i, t in enumerate(trades, 1):
        cum_pnl += t['net_pnl']
        eq += t['net_pnl']
        t_open = datetime.fromtimestamp(t.get('opened_at', 0)).strftime('%H:%M:%S') if t.get('opened_at') else '?'
        t_close = datetime.fromtimestamp(t.get('closed_at', 0)).strftime('%H:%M:%S') if t.get('closed_at') else '?'
        print(f"  #{i:>2} [{t_close}] {t['symbol']:<6} | Qty: {t['quantity']:>4} | Open: {t_open} | Held: {t.get('held_minutes')}m | In: {t['entry_price']:>9.2f} | Out: {t['exit_price']:>9.2f} | Gross: ${t['gross_pnl']:>8.2f} | Fees: ${t['fees']:>7.2f} | Net: ${t['net_pnl']:>8.2f} | Cum PnL Today: ${cum_pnl:>9.2f} | Equity: ${eq:>11,.2f} | Reason: {t['reason']}")
else:
    print("No trades found.")

# Inspect decisions
print(f"\nTotal decisions: {len(decisions)}")
approved = [d for d in decisions if d.get('approved')]
rejected = [d for d in decisions if not d.get('approved')]
print(f"Approved: {len(approved)} | Rejected: {len(rejected)}")
rej_reasons = Counter()
for d in rejected:
    for r in d.get('reasons', []):
        rej_reasons[r] += 1
print("\nTop rejection reasons:")
for r, cnt in rej_reasons.most_common(10):
    print(f"  [{cnt:>3}] {r}")

# Check logs for circuit breakers, halts, or errors
print("\nWarning / Error / Circuit Breaker logs:")
for l in logs:
    lvl = l.get('level', '')
    msg = l.get('message', '')
    if lvl in ('warning', 'error') or 'circuit' in msg.lower() or 'pérdida' in msg.lower() or 'halt' in msg.lower():
        print(f"  [{lvl.upper()}] {l.get('source')}: {msg}")
