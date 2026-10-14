"""Backtest rápido sobre el simulador (sin servidor ni UI).

Uso:  python -m scripts.simulate --minutes 360 --runs 5
Útil para calibrar parámetros de riesgo antes de operar. Los resultados del simulador
NO predicen resultados reales.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics

from app.config import load_settings
from app.data.simulator import SimulatedFeed
from app.orchestrator import TradingSystem


async def one_run(minutes: int, seed: int) -> dict:
    settings = load_settings()
    s = TradingSystem(settings)
    s.feed = SimulatedFeed(settings.universe, seed=seed)
    s.execution.ORDER_TIMEOUT_S = 0
    await s.start()
    if s.loop_task:
        s.loop_task.cancel()
    for _ in range(minutes):
        if s.state.value == "HALTED":
            break
        await s.tick()
    await s.stop("Fin de backtest", manual=False)
    k = s.snapshot()["kpis"]
    reasons = {}
    for t in s.trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {"seed": seed, "pnl": k["pnl"], "pnl_pct": k["pnl_pct"], "trades": k["trades"],
            "win_rate": k["win_rate"], "pf": k["profit_factor"], "fees": k["fees"], "halted": s.chief.day.halted_reason,
            "exits": reasons}


async def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=360)
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    res = [await one_run(a.minutes, random.randint(1, 10_000)) for _ in range(a.runs)]
    for r in res:
        wr = f"{r['win_rate']:.0%}" if r["win_rate"] is not None else "—"
        print(f"seed={r['seed']:>5} pnl={r['pnl']:>12,.2f} ({r['pnl_pct']:+.2%}) trades={r['trades']:>3} "
              f"win={wr:>4} fees={r['fees']:>10,.2f} halted={r['halted'] or '-'} exits={r['exits']}")
    print(f"\nPromedio P&L%: {statistics.mean(r['pnl_pct'] for r in res):+.3%}  |  "
          f"peor: {min(r['pnl_pct'] for r in res):+.3%}  |  mejor: {max(r['pnl_pct'] for r in res):+.3%}")


if __name__ == "__main__":
    asyncio.run(main())
