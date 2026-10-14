# AGENTS.md – Reglas del sistema multi-agente "Investments"

Estas reglas aplican a cualquier agente de IA (Antigravity, Claude Code, etc.) que trabaje en este repositorio
y a los agentes de trading implementados en `app/agents/`. Las skills detalladas están en `.agents/skills/`.

## Jerarquía
```
Analista Jefe de Mercado (chief)  ← poder de veto, supervisión continua, circuit breakers
├── Analista de Conexión a Mercados/Brokers (broker_analyst)
├── Analista de Riesgo 1-5 min (risk_analyst)
├── Analista de Múltiples Carteras 80/20 (portfolio_manager)
└── Analista de Ejecución (execution)
```

## Reglas no negociables
1. **Ninguna orden llega al mercado sin aprobación del Analista Jefe.**
2. **Modo PAPER por defecto.** Dinero real sólo con `ALLOW_LIVE_TRADING=true` + frase de confirmación en la UI.
3. **Nunca** commitear credenciales, tokens ni `.env`. Credenciales sólo en memoria o `.env`.
4. **Nunca** operar real con precios simulados o demorados (Yahoo Finance tiene demora).
5. **Nunca** relajar límites de riesgo para "recuperar" pérdidas. Cambios de límites: sólo con el sistema detenido
   y documentados en el commit.
6. Toda decisión queda registrada en `journal/AAAA-MM-DD.jsonl` (auditoría).
7. Cualquier cambio en la lógica de agentes debe pasar `pytest` y `python -m scripts.simulate`.

## Convenciones de código
- Python 3.11+, tipado, sin dependencias pesadas en el núcleo (indicadores en Python puro).
- Configuración en `config/settings.yaml`; nada de números mágicos en los agentes.
- Mensajes y logs en español (usuario final argentino).
