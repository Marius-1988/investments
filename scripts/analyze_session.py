import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
with urllib.request.urlopen("http://127.0.0.1:8000/api/state") as res:
    data = json.loads(res.read().decode())

trades = data.get("trades", [])
print(f"Session Trades: {len(trades)}")
reasons = {}
for t in trades:
    r = t["reason"]
    reasons[r] = reasons.get(r, 0) + 1
    print(f"{t['symbol']:<6} | Qty:{t['quantity']:>4} | In:{t['entry_price']:>9.2f} | Out:{t['exit_price']:>9.2f} | Held:{t['held_minutes']:>2}m | Gross:{t['gross_pnl']:>8.1f} | Fees:{t['fees']:>7.1f} | Net:{t['net_pnl']:>8.1f} | Reason: {r}")

print("\nExit summary:", reasons)
