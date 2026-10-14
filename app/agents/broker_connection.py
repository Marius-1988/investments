"""Subagente: Analista de Conexión a Mercados / Brokers.

Recomienda el mejor canal de acceso para operar de forma automatizada en Argentina y guía
al usuario para validar y establecer la conexión. Nunca conecta sin confirmación explícita.
"""
from __future__ import annotations

from typing import Dict, List

from .base import Agent

# Catálogo curado. Los costos cambian: verificar siempre con el broker antes de operar.
CATALOG: List[Dict] = [
    {
        "id": "primary",
        "name": "Primary API (Matba Rofex) vía pyRofex",
        "kind": "API de mercado vía ALyC",
        "official_api": True, "paper_env": True, "adapter": True, "realtime": True,
        "cost_score": 0.8, "coverage_score": 0.9,
        "markets": "BYMA (acciones, bonos, CEDEARs) y futuros MATba-ROFEX",
        "pros": ["Entorno demo gratuito reMarkets para probar sin dinero",
                 "Market data y ruteo de órdenes en tiempo real (REST + WebSocket)",
                 "Estándar de la industria para trading algorítmico en Argentina"],
        "cons": ["Para operar real se necesita un ALyC que habilite Primary API (URL propia)",
                 "reMarkets lista un subconjunto de instrumentos"],
        "fields": [{"key": "user", "label": "Usuario"}, {"key": "password", "label": "Contraseña", "secret": True},
                   {"key": "account", "label": "Cuenta/Comitente"},
                   {"key": "environment", "label": "Entorno (REMARKET | LIVE)", "default": "REMARKET"}],
        "signup": "https://remarkets.primary.ventures",
    },
    {
        "id": "iol",
        "name": "InvertirOnline (IOL) – API REST",
        "kind": "ALyC con API pública",
        "official_api": True, "paper_env": False, "adapter": True, "realtime": True,
        "cost_score": 0.6, "coverage_score": 0.85,
        "markets": "BYMA (acciones, bonos, CEDEARs, cauciones)",
        "pros": ["API pública documentada, alta de API desde la cuenta", "Apertura de cuenta 100% online"],
        "cons": ["Sin entorno demo oficial: probar primero con el broker paper del sistema",
                 "Límites de requests: cotizaciones vía polling"],
        "fields": [{"key": "username", "label": "Usuario IOL"}, {"key": "password", "label": "Contraseña", "secret": True}],
        "signup": "https://www.invertironline.com",
    },
    {
        "id": "ppi",
        "name": "Portfolio Personal Inversiones (PPI) – API",
        "kind": "ALyC con API",
        "official_api": True, "paper_env": True, "adapter": False, "realtime": True,
        "cost_score": 0.7, "coverage_score": 0.85,
        "markets": "BYMA, CEDEARs, bonos, FCI",
        "pros": ["Cliente Python oficial con sandbox", "Streaming de precios"],
        "cons": ["Adaptador aún no implementado en este proyecto (roadmap)"],
        "fields": [], "signup": "https://www.portfoliopersonal.com",
    },
    {
        "id": "cocos",
        "name": "Cocos Capital",
        "kind": "ALyC (app)",
        "official_api": False, "paper_env": False, "adapter": False, "realtime": True,
        "cost_score": 0.8, "coverage_score": 0.8,
        "markets": "BYMA, CEDEARs, bonos",
        "pros": ["Costos competitivos para operar manualmente"],
        "cons": ["Sin API pública oficial: no recomendado para bots (riesgo operativo y de TyC)"],
        "fields": [], "signup": "https://cocos.capital",
    },
    {
        "id": "paper",
        "name": "Simulador interno (paper trading)",
        "kind": "Simulación",
        "official_api": True, "paper_env": True, "adapter": True, "realtime": True,
        "cost_score": 1.0, "coverage_score": 0.5,
        "markets": "Universo configurado (simulado o Yahoo Finance con demora)",
        "pros": ["Cero riesgo: validar estrategia y límites antes de usar dinero real"],
        "cons": ["No opera en el mercado real"],
        "fields": [], "signup": None,
    },
]

WEIGHTS = {"official_api": 0.30, "paper_env": 0.20, "adapter": 0.20, "cost_score": 0.15, "coverage_score": 0.15}


class BrokerConnectionAnalyst(Agent):
    name = "broker_analyst"
    title = "Analista de Conexión a Mercados/Brokers"
    mission = ("Recomendar el mejor broker/canal API para operar automáticamente, validar con el usuario "
               "y establecer la conexión de forma segura (credenciales sólo en memoria / .env).")
    skills = ["broker-connection-analyst"]

    def recommend(self) -> dict:
        ranked = []
        for b in CATALOG:
            score = sum(w * (float(b[k]) if not isinstance(b[k], bool) else (1.0 if b[k] else 0.0))
                        for k, w in WEIGHTS.items())
            ranked.append({**b, "score": round(score * 100, 1)})
        real = sorted([b for b in ranked if b["id"] != "paper"], key=lambda x: x["score"], reverse=True)
        best = real[0]
        return {
            "ranking": real + [b for b in ranked if b["id"] == "paper"],
            "recommended": best["id"],
            "plan": [
                "1. Operar 2-4 semanas en modo PAPER (simulador o Yahoo con demora) y revisar métricas.",
                f"2. Conectar {best['name']} en entorno DEMO (reMarkets) para validar órdenes reales sin dinero.",
                "3. Pasar a LIVE con un capital chico (5-10% del total) y límites de pérdida diarios estrictos.",
                "4. Escalar sólo si profit factor > 1.3 y drawdown dentro de límites tras ≥ 100 operaciones.",
            ],
            "direct_market_access": (
                "No es posible operar en BYMA sin intermediario: la normativa CNV exige un ALyC registrado. "
                "La alternativa más 'directa' es Primary API (acceso DMA a través de un ALyC), que es lo que "
                "usan los algos profesionales en Argentina."
            ),
        }
