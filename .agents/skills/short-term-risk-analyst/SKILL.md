---
name: short-term-risk-analyst
description: >-
  Analista de Riesgo de la Operación para ventanas cortas (1-5 minutos). Usar para medir volatilidad,
  ATR, spread y liquidez por activo, clasificar riesgo LOW/MEDIUM/HIGH, detectar setups de momentum
  y rankear en qué activo conviene operar considerando la ventaja neta de costos.
---

# Analista de Riesgo (ventana 1-5 min)

Código: [`app/agents/risk_analyst.py`](../../../app/agents/risk_analyst.py) · Indicadores: [`app/indicators.py`](../../../app/indicators.py)

## Métricas por activo (velas de 1 minuto)
- **Volatilidad 1m**: desvío de retornos de 30 velas. Clasificación dinámica: < 0.12% LOW, < 0.28% MEDIUM, resto HIGH.
- **Riesgo final** = el más alto entre el riesgo estático (config) y el dinámico (medido en vivo).
- **ATR(14)** para stops/objetivos; **spread %** de las puntas; **z-score de volumen** (liquidez).
- **Ratio de volatilidad** 10/60 min (expansión = peligro).
- **Risk score 0-100** = volatilidad (45) + spread (20) + expansión de volatilidad (20) + baja liquidez (15).

## Setup de entrada (long)
| Condición | Peso |
|-----------|------|
| EMA5 > EMA20 | 0.22 |
| Precio > VWAP | 0.18 |
| RSI entre 52 y 70 (impulso sin sobrecompra) | 0.15 |
| Momentum 3 min > 0 | 0.15 |
| Volumen sobre la media | 0.10 |
| Volatilidad estable (ratio < 1.6) | 0.10 |
| Spread aceptable | 0.10 |

- Entrada = ask · Stop = entrada − 1.5×ATR · Objetivo = entrada + 2×riesgo.
- Horizonte estimado = (distancia al objetivo / ATR)² / 2, acotado a 1-5 min.
- **Ranking de oportunidad** = confianza × min(3, objetivo/costo) / (1 + riskScore/50).

## Advertencias de experto
- En ventanas de 1-5 min el ruido domina: la ventaja estadística es pequeña y **los costos la consumen**.
  Si `edge_vs_cost < 2`, el setup no vale la pena aunque la señal sea "linda".
- Evitar activos con spread > 0.6% o volumen anómalamente bajo.
- Los indicadores se recalculan sólo al cierre de cada vela (no repintar señales intra-vela).
