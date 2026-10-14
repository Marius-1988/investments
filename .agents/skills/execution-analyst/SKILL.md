---
name: execution-analyst
description: >-
  Analista de Ejecución de Operaciones. Usar para enviar órdenes de compra/venta aprobadas por el Analista
  Jefe con órdenes límite protegidas, controlar slippage y fills parciales, y gestionar salidas
  (stop loss, take profit, break-even, trailing stop, salida por tiempo y cierre de emergencia).
---

# Analista de Ejecución

Código: [`app/agents/execution.py`](../../../app/agents/execution.py) · Brokers: [`app/brokers/`](../../../app/brokers/)

## Mejores prácticas de ejecución aplicadas
1. **Sólo órdenes límite** (nunca "a mercado" puro): compra a `ask × (1 + 0.2%)`, venta a `bid × (1 − 0.2%)`.
2. **Control de slippage**: si el ask ya se alejó más de 0.2% del precio analizado → se aborta la entrada.
3. **Timeout de 8 s**: si la orden no se completa, se cancela; fills parciales se registran tal cual.
4. **Salidas primero**: en cada ciclo se gestionan posiciones abiertas antes de evaluar entradas.
5. **Valuación a precio de liquidación** (bid), no al último operado.

## Gestión de la posición
| Evento | Acción |
|--------|--------|
| Precio ≤ stop | Venta (STOP_LOSS o TRAILING_STOP) |
| Precio ≥ objetivo | Venta (TAKE_PROFIT) |
| +1R de ganancia | Stop a break-even + costos |
| ≥ +1R | Trailing stop a 1.2×ATR del máximo favorable |
| 5 minutos abiertos | Venta (TIME_STOP) – la tesis de corto plazo expiró |
| Orden del Jefe (CHAOTIC / circuit breaker / cierre de mercado / kill switch) | Venta urgente (slippage permitido x3) |

## Si una venta no se ejecuta
Se reintenta en el siguiente ciclo y se loguea como `warning`. Nunca se abandona una posición sin gestionar.
