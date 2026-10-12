# ADR 0004 — Hipótesis H-CARRY-1: carry de divisas (diferencial de tasas)

- Fecha: 2026-10-12
- Estado: aceptada (pre-registro: escrita **antes** de ejecutar cualquier prueba)

## Contexto

Cinco hipótesis basadas en patrones de precio (familia `baseline-v001` en M15/H1/H4, con y sin filtro macro) no pasaron la Puerta A. Se cambia de tipo de idea: una prima de riesgo con fundamento económico y documentada en la literatura académica, el **carry**. Mantener una posición larga en la moneda de mayor tasa y corta en la de menor tasa cobra el diferencial de tasas cada día (swap), a cambio de riesgo de caídas bruscas.

Prior honesto: **moderado-bajo** para este periodo. Entre 2010 y 2021 las tasas de casi todas estas monedas estuvieron cerca de cero, así que los diferenciales (y el carry) eran pequeños frente a los costes.

## Universo y datos

- Pares (D1, MetaQuotes-Demo, desde 2010-09): EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF (8 monedas).
- Tasas: FRED `IR3TIB01{CC}M156N` (interbancaria a 3 meses, mensual, OECD) para US, EZ, GB, JP, AU, NZ, CA, CH.
- **Sin look-ahead:** el valor del mes M (fechado el día 1 de M) se considera disponible desde el **día 1 del mes M+2** a las 00:00 UTC.

## Reglas (versión `carry-v001`)

1. **Rebalanceo mensual**, al cierre de la primera vela D1 de cada mes.
2. Para cada par, diferencial `d = tasa(base) − tasa(cotizada)` con las últimas tasas disponibles.
3. Candidatos: pares con `|d| ≥ 0.50` puntos porcentuales; dirección LONG si `d > 0`, SHORT si `d < 0`.
4. Se mantienen como máximo **3 posiciones** (techo de `risk-policy.md`): las 3 de mayor `|d|`.
5. Una posición abierta se **cierra en el rebalanceo** si deja de estar entre las 3 elegidas o cambia de dirección (salida al cierre de esa vela).
6. **Stop-loss** a 3 × ATR(20, D1) desde la entrada. El take-profit es obligatorio en el contrato y se fija a 20 × ATR (no vinculante en la práctica). Tras un stop, el par solo vuelve a entrar en el siguiente rebalanceo.
7. Tamaño: el gestor de riesgo estándar, 0.25 % de riesgo hasta el stop por posición (≤ 0.75 % en total).

## Riesgo y costes específicos

- `RiskLimits`: `max_open_positions=3`, `max_trades_per_day=10`, `max_consecutive_losses=5`, resto como en el MVP.
- Exposición por divisa: con 3 posiciones contra USD el límite de 1× riesgo bloquearía la estrategia por construcción; se usa `currency_exposure_mult = 3` (riesgo agregado por divisa ≤ 0.75 %, igual al total permitido).
- Spreads fijos: EURUSD 12, GBPUSD 16, USDJPY 14, AUDUSD 14, NZDUSD 18, USDCAD 18, USDCHF 16 puntos; slippage 2 puntos.
- **Swap modelado**: por cada día natural con la posición abierta, `notional_USD × (tasa_larga − tasa_corta − 1.0 %) / 365`. El 1 % anual representa el margen del broker sobre el swap y se paga siempre, en ambas direcciones (conservador).

## Variantes vecinas para A9 (fijadas aquí)

`|d| ≥ 0.25`, `|d| ≥ 1.00`, stop 2 × ATR, stop 4 × ATR, rebalanceo semanal (primera vela de la semana), máximo 2 posiciones.

## Criterio de éxito

La Puerta A de la ADR 0002, sin cambios. Hold-out de 12 meses: **no se usa** en esta corrida. Si falla, se descarta `carry-v001`; cualquier variante nueva necesita su propia ADR escrita antes de evaluarla.
