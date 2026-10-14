---
name: multi-portfolio-manager
description: >-
  Analista de Múltiples Carteras. Usar para asignar capital entre carteras por perfil de riesgo
  (conservador: 80% bajo/medio, 20% alto), dimensionar posiciones por riesgo fijo, controlar límites
  por cartera y reportar asignación objetivo vs. real.
---

# Analista de Múltiples Carteras

Código: [`app/agents/portfolio_manager.py`](../../../app/agents/portfolio_manager.py)

## Estructura (perfil conservador)
| Cartera | Peso | Riesgos admitidos | Posiciones máx. |
|---------|------|-------------------|-----------------|
| Conservadora | 80% | LOW, MEDIUM (bonos soberanos, panel líder) | 4 |
| Agresiva | 20% | HIGH (panel general / alta volatilidad) | 2 |

El capital de cada cartera = asignación inicial + P&L realizado propio (las pérdidas de la agresiva
**no** contaminan a la conservadora).

## Dimensionamiento (fixed fractional)
```
riesgo_por_unidad = (entrada − stop) + entrada × costo_ida_vuelta
qty = min( capital_cartera × 0.5% / riesgo_por_unidad,     # riesgo fijo por operación
           capital_cartera × 25% / entrada,                 # tope por posición
           caja_disponible_cartera / (entrada × (1+costo)) ) # liquidez
```
El Analista Jefe puede reducir el tamaño (x0.5 en régimen VOLATILE).

## Reglas
- Una sola posición por activo.
- Sin apalancamiento ni short (long-only por defecto).
- Reportar en el dashboard: capital, invertido, utilización, P&L realizado/no realizado y win rate por cartera.
- Rebalanceo: al inicio de cada día se recalculan los pesos objetivo sobre el equity vigente
  (reiniciar el servidor o ajustar `capital_ars`).
