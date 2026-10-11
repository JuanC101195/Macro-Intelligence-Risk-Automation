# Política de riesgo

> Aplica a backtest, paper y demo. El riesgo es independiente de la estrategia, el ML, Crucix, n8n y cualquier LLM.

## 1. Límites del MVP

| Límite | Default | Techo duro (validado en config) |
|--------|---------|---------------------------------|
| `max_risk_per_trade` | 0.0025 (0.25 %) | 0.005 |
| `max_daily_loss` | 0.02 | 0.02 |
| `max_open_positions` | 1 | 3 |
| `max_symbol_exposure` | 1 posición por símbolo | 1 |
| `max_consecutive_losses` | 3 | 5 |
| `max_spread_points` | 30 (EURUSD/GBPUSD), configurable por símbolo | — |
| `max_slippage_points` | 10 | — |
| `max_trades_per_day` | 5 | 10 |
| `max_currency_exposure` | riesgo abierto por divisa ≤ 1 × `max_risk_per_trade` | — |

Nota: `CLAUDE.md` pone `MAX_RISK_PER_TRADE=0.005` en su ejemplo de `.env`. En este proyecto ese valor es el **techo**; el default (y el de `.env.example`) es 0.0025.

### Exposición por divisa

EURUSD y GBPUSD están muy correlacionados: un LONG en ambos equivale a ir corto en USD dos veces. El límite por símbolo no lo detecta. Por eso cada posición se descompone en sus dos divisas (LONG EURUSD = +EUR, −USD) y se rechaza una orden nueva si el riesgo abierto en la misma dirección sobre una divisa supera `max_currency_exposure`. Con los defaults del MVP (`max_open_positions=1`) no puede pasar, pero la regla debe existir antes de subir ese límite.

Cambiar un límite requiere confirmación explícita y queda registrado en `system_events`. Ningún cambio puede superar el techo duro.

## 2. Cálculo de lotaje

```text
risk_money      = equity × risk_percent             (equity, no balance)
stop_distance   = |entry - stop_loss|
ticks_to_stop   = stop_distance / tick_size
loss_per_lot    = ticks_to_stop × tick_value         (tick_value en divisa de la cuenta)
raw_volume      = risk_money / loss_per_lot
volume          = floor(raw_volume / volume_step) × volume_step
```

Precio de entrada: en paper/demo, `entry` es el **ask** (LONG) o el **bid** (SHORT) del tick actual, no el `close` de la vela de la señal. El precio pudo moverse entre el cierre de la vela y la orden: el SL propuesto se conserva como precio y el volumen se recalcula con la distancia real. Si la distancia real queda fuera del rango permitido en ATR, se rechaza.

Reglas:

- Si `volume < volume_min` ⇒ **rechazar** (no se redondea hacia arriba: eso aumentaría el riesgo).
- Si `volume > volume_max` ⇒ recortar a `volume_max`.
- Recalcular el riesgo real con el volumen final; debe ser ≤ `risk_money`.
- `stop_distance` debe cumplir `≥ stops_level_points × point` y una distancia mínima en ATR.
- Comprobar margen con `order_calc_margin` de MT5: `margin_required(volume) ≤ margin_free × 0.5`.
- Verificación cruzada: `order_calc_profit(entry → SL, volume)` debe coincidir con `-risk_real` (±1 %). Si no coincide, se rechaza: indica un `tick_value` mal interpretado.
- **Pérdida diaria en el peor caso:** `pérdida_realizada_hoy + riesgo_hasta_SL_de_posiciones_abiertas + riesgo_de_la_nueva ≤ max_daily_loss × equity_inicio_día`. Sin esta regla, varias posiciones abiertas podrían terminar superando el 2 % aunque cada una cumpla su límite.
- Siempre redondeo **hacia abajo**.

### `tick_value` y divisa de la cuenta

`tick_value` de MT5 ya viene en la divisa de la cuenta, pero para pares cuya divisa de beneficio no es la de la cuenta (USDJPY en cuenta USD) **cambia con el precio**. Por eso:

- en paper/demo se lee de `SymbolSpec` en el momento de la orden;
- en backtest se recalcula por vela: `tick_value = tick_size × contract_size / price_conversion`.

### Ejemplo — EURUSD, cuenta USD

```text
equity 10 000 USD, riesgo 0.25 % → risk_money = 25 USD
entry 1.08250, SL 1.08050 → stop_distance = 0.00200
tick_size 0.00001, tick_value 1.0 USD/lote → ticks = 200, loss_per_lot = 200 USD
raw_volume = 25 / 200 = 0.125 → volume_step 0.01 → 0.12 lotes (riesgo real 24 USD)
```

### Ejemplo — USDJPY, cuenta USD

```text
equity 10 000 USD, riesgo 0.25 % → 25 USD
entry 150.000, SL 149.700 → stop_distance = 0.300
tick_size 0.001, contract 100 000 → 100 JPY por tick por lote
tick_value ≈ 100 / 150.000 = 0.6667 USD
ticks = 300 → loss_per_lot = 200 USD → 0.125 → 0.12 lotes
```

Ambos ejemplos se convierten en tests unitarios en la Fase 5. Si la cuenta demo no está en USD, también EURUSD y GBPUSD necesitan conversión; la divisa se confirma en la Fase 2.

### Precios bid/ask

Las velas de MT5 son de precio **bid**. Por tanto:

| Lado | Entrada | SL/TP se disparan cuando |
|------|---------|--------------------------|
| LONG | ask = bid + spread | el **bid** toca SL o TP |
| SHORT | bid | el **ask** (= bid + spread) toca SL o TP |

En el backtest, un SHORT se cierra en `high + spread ≥ SL`, no en `high ≥ SL`. Ignorar esto hace que los SHORT parezcan mejores de lo que son.

## 3. Stops y take-profit

- Toda orden lleva SL y TP. No hay órdenes sin SL.
- SL inicial basado en ATR (default 1.5 × ATR14), dentro de [min, max] en puntos por símbolo.
- TP default = 2 × distancia del SL (R:R 1:2), configurable.
- Ningún componente puede quitar o ensanchar un SL después de abierta la posición. Moverlo a break-even o trailing (solo hacia la dirección favorable) queda para una fase posterior.

## 4. Circuit breaker

Se abre (bloquea operaciones nuevas, no cierra las existentes) cuando:

| Condición | Origen |
|-----------|--------|
| Pérdida diaria ≥ `max_daily_loss` (realizada + flotante, sobre equity al inicio del día de trading) | risk |
| `max_consecutive_losses` alcanzado | risk |
| MT5 desconectado > N segundos | broker / health |
| Posición no reconciliable (existe en broker y no en BD, o al revés) | reconciliation |
| `intent_id` duplicado | execution |
| Modelo activo vencido (`expires_at`) | models |
| Datos obsoletos (última vela > 2 timeframes) | trading_loop |
| Spread > límite en N velas consecutivas | risk |
| Errores consecutivos de API/broker > umbral | monitoring |
| Arranque con estado inconsistente | startup |
| Cuenta conectada no es demo estando en modo demo | execution |

- **Día de trading:** empieza a las 17:00 de Nueva York (rollover FX, 21:00/22:00 UTC según horario de verano), no a medianoche UTC. Medianoche UTC partiría la sesión asiática en dos días distintos.
- **Reset solo manual**, vía API con confirmación y operador. Nunca automático.
- El kill switch es un breaker con motivo `manual_kill`; además puede (opcional, configurable) cerrar posiciones abiertas.
- El estado se persiste y se muestra en `/health` y en el dashboard.

## 5. Costes

Todo resultado (backtest, paper, reportes) incluye spread, comisión, slippage y swap. Un resultado sin costes no se reporta como resultado financiero.
