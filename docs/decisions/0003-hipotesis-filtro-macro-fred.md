# ADR 0003 — Hipótesis H-MACRO-1: filtro de régimen macro con historia de FRED

- Fecha: 2026-10-12
- Estado: aceptada (pre-registro: escrita **antes** de ejecutar cualquier prueba)

## Contexto

`baseline-v001` (tendencia EMA + pullback RSI + MACD + ADX) no pasó la Puerta A en M15, H1 ni H4 (ver `progress.md`). La ADR 0002 propone como segundo pivote usar el contexto macro **como filtro de cuándo no operar**. Con Crucix no se puede probar todavía (no tiene historia), pero las mismas variables existen en FRED con décadas de historia diaria.

## Hipótesis

Las pérdidas de `baseline-v001` se concentran en regímenes macro desfavorables a la dirección de la operación. Filtrando por régimen, la estrategia resultante pasa la Puerta A.

Prior honesto: **bajo**. Un filtro solo elimina operaciones; si las pérdidas están repartidas entre regímenes, no crea ventaja.

## Datos y sin look-ahead

| Variable | Serie FRED | Inicio |
|----------|-----------|--------|
| VIX | `VIXCLS` | 1990 |
| Spread high yield | `BAMLH0A0HYM2` | 1996 |
| Curva 10Y-2Y | `T10Y2Y` | 1976 |

- Un valor fechado el día D se considera **disponible a partir de D+1 a las 22:00 UTC** (conservador: FRED publica varias series con un día de retraso).
- `vix_change_pct` = variación porcentual de `VIXCLS` respecto a la observación anterior.
- Oro: sin serie diaria gratuita vigente en FRED ⇒ `None` (el clasificador ya lo admite).
- Contexto `stale` si la última observación disponible tiene más de 4 días.
- Clasificador: **`regime-rules-v001` sin cambios** (umbrales fijados en la Fase 3).

## Variantes (fijadas aquí; nada más se prueba)

| Versión | Regla |
|---------|-------|
| `baseline-v001-h1-macro-block` | risk_off bloquea LONG, risk_on bloquea SHORT; contexto `unknown`/`stale` ⇒ HOLD |
| `baseline-v001-h1-macro-confirm` | LONG solo en risk_on, SHORT solo en risk_off; el resto ⇒ HOLD |

- Timeframe: **H1** (15 años de historia de investigación, la muestra más grande).
- Cada variante corre con costos ×1/×1.5/×2, walk-forward y las 6 vecinas de A9 (que heredan el filtro).
- Presupuesto: 2 variantes principales + 12 vecinas = 14 de las 20 de esta hipótesis.
- Hold-out de 12 meses: **no se usa**.

## Criterio de éxito

La Puerta A de la ADR 0002, sin cambios. Si ninguna variante pasa:
- se descarta el filtro macro sobre esta familia de señales;
- la historia de FRED se reutiliza para hipótesis con fundamento económico propio (carry / diferencial de tasas), en una ADR nueva.
