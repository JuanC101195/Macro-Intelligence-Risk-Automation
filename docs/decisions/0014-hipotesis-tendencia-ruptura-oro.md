# ADR 0014 — Hipótesis: tendencia EMA 50/200 + ruptura de 20 velas en oro (H4 y D1)

- Fecha: 2026-10-13
- Estado: aceptada (pre-registro: escrita **antes** de escribir código o ejecutar cualquier prueba de esta hipótesis)
- Hipótesis: `trendbo-xau-v001`. Usa **10 de las 20** variantes del presupuesto de la ADR 0002 (8 principales + 2 controles).
- Número: la ADR 0013 queda reservada para la evaluación del historial del socio.

## Contexto

El 2026-10-13 Juan trajo un prompt externo de "ingeniero cuantitativo" para XAUUSD. Las reglas que propone son: EMA 50/200 como filtro de tendencia, ruptura del máximo o mínimo de las 20 velas cerradas anteriores, ATR(14) para el stop, riesgo del 0.5 % por operación y comparar varios métodos de salida. Su método de validación (costes, separación de datos, walk-forward, robustez, demo antes que dinero real) ya es el nuestro, y el nuestro es más estricto: pre-registro, hold-out de un solo uso y A11 contra entradas aleatorias.

Lo nuevo frente a lo ya probado es **la combinación** filtro EMA 50/200 + canal 20 + **solo oro**. Las rupturas de las ADR 0006 y 0008 (canal 55/20, cartera de 11 instrumentos, sin filtro de tendencia) incluían el oro dentro de la cartera. Elegir el oro **no** sale de esos resultados: viene del prompt y de que es el mercado que opera el socio. Aun así se deja escrito como riesgo de sesgo.

Prior honesto: **bajo**. Es la estrategia de tendencia más conocida sobre el oro, y las rupturas probadas dieron PF ≈ 0.92. Además, un filtro cualquiera sobre la ruptura ya la subía a PF ≈ 1.00 (ADR 0009). Por eso la comparación contra el azar (A11) es la que decide.

## Reglas (todas las versiones)

Instrumento **XAUUSD**. Todo se calcula al cierre de cada vela, solo con velas cerradas.

- **Tendencia:** EMA(50) y EMA(200) de los cierres. Solo compras si EMA50 > EMA200, solo ventas si EMA50 < EMA200. Mientras alguna no esté lista, no se opera.
- **Entrada:** compra si el cierre supera el **máximo de las 20 velas anteriores** (la actual no cuenta); venta si el cierre queda por debajo del **mínimo de las 20 anteriores**. La orden se llena en la apertura de la vela siguiente (convención del motor).
- **Stop inicial:** 2 × ATR(14) desde la entrada. El stop nunca se aleja.
- **Lotaje:** lo calcula el gestor de riesgo: **0.5 %** por operación, capital **17 500** (equivalente cent, ADR 0005), contrato de MT5 (100 oz, lote mínimo 0.01, paso 0.01). Si el lote calculado queda por debajo de 0.01, **no se opera** (rechazo `volume_below_min`, que se reporta). Nunca lote fijo.
- **Límites:** 1 posición, pérdida diaria 2 %, 5 pérdidas seguidas, 10 operaciones por día. Límites de spread y slippage del gestor desactivados (costes fijos modelados, como en la ADR 0006).
- **Costes:** spread 30 puntos, slippage 5 puntos y financiación del oro según la ADR 0006 (largo paga la tasa USD + 1 %, corto paga 1 %; tasas FRED).
- **No incluido:** la regla de "estructura de máximos y mínimos crecientes" del prompt queda fuera, porque no tiene una definición mecánica sin parámetros extra. Tampoco hay filtro de noticias, porque no tenemos un calendario histórico. Si alguna se agrega, será una hipótesis nueva.

## Las cuatro salidas

| Salida | Regla (al cierre; efecto en la vela siguiente) | Take-profit |
|---|---|---|
| `channel` | Ruptura contraria: compra sale si el cierre < mínimo de las **10** velas anteriores; venta si el cierre > máximo de las 10 anteriores | No vinculante (20 × ATR, piso del 10 % en ventas) |
| `trailing` | Stop móvil tipo *chandelier*: compra = máximo alto desde la entrada − 2 × ATR(14) actual; venta = mínimo bajo desde la entrada + 2 × ATR(14). Solo se acerca | No vinculante |
| `invalidation` | Sale en la vela en que la EMA50 **cruza** a la EMA200 en contra de la posición (cruce, no estado) | No vinculante |
| `target` | Solo stop y objetivo fijo | **2 R** (4 × ATR(14) desde la entrada) |

En `invalidation` se usa el cruce y no el estado. Así, en el modelo nulo (A11) una entrada aleatoria contra la tendencia no sale de inmediato, lo que bajaría artificialmente al azar.

## Versiones pre-registradas (10)

| Versión | Temporalidad | Filtro EMA | Salida |
|---|---|---|---|
| `trendbo-xau-h4-{channel,trailing,invalidation,target}` | H4 | sí | las 4 |
| `trendbo-xau-d1-{channel,trailing,invalidation,target}` | D1 | sí | las 4 |
| `trendbo-xau-h4-channel-nofilter` (control) | H4 | no | `channel` |
| `trendbo-xau-d1-channel-nofilter` (control) | D1 | no | `channel` |

Los controles miden si el filtro EMA aporta algo frente a la misma ruptura sin filtro. Las 10 cuentan en el presupuesto.

## Datos y periodo

XAUUSD H4 y D1 de MetaQuotes-Demo ya descargados (desde 2004), con hash. Se opera desde la primera vela en que EMA200, canal y ATR están listos hasta el inicio del hold-out (12 meses, bloqueado). Ambos tienen más de 3 años (A1).

Advertencia escrita antes de correr: en **D1**, una ruptura con filtro opera pocas veces (del orden de 5–10 por año), así que **A2 (≥ 300 operaciones) probablemente falla por construcción**. Se corre igual, porque está pre-registrado. Un D1 que pase todo menos A2 no se aprueba: como mucho queda como candidato para medirlo hacia adelante.

Advertencia de lote: con 0.5 % de 17 500 (87.5) y el contrato de 100 oz, un stop de 2 × ATR mayor que **87.5 USD por onza** queda por debajo de 0.01 lotes y se rechaza. Es probable en D1 en los años recientes (oro > 2 500 USD). Es la restricción real de la cuenta, no se corrige: se reporta cuántas señales se rechazaron así.

## Criterio de éxito

- **Puerta A completa (A1–A11, ADR 0002 y 0010)** para cada versión, con costes ×1, ×1.5 y ×2, ventanas de 6 meses y 200 versiones con entradas aleatorias (A11, misma gestión de salida).
- **A9 (vecinas, fijadas aquí):** EMA 40/160 · EMA 60/240 · canal de entrada 15 · canal de entrada 25 · stop 1.5 × ATR · stop 2.5 × ATR.
- **Pruebas múltiples:** son 10 pruebas. Si pasa una sola versión, es una evidencia débil y se dirá así: pasa a medición hacia adelante (paper/demo, Fase 7), no a dinero real. El hold-out se usa una sola vez y solo sobre la versión que haya pasado; si pasan varias, se elige **antes** de abrirlo con una regla escrita en una adenda.
- **Lectura informativa (no decide nada):** filtro frente a control, rechazos por lote mínimo y resultado con 0.01 lote fijo.
- **Si ninguna pasa:** se cierra la familia de seguimiento de tendencia por ruptura en el oro, en cualquier temporalidad, salvo una razón nueva registrada antes de correr.

## Consecuencias

- La estrategia se implementa como un módulo nuevo (`strategy/trend_breakout.py`) y una suite propia, sin cambiar las estrategias anteriores.
- No se afina nada después de ver resultados. Quedan 10 variantes del presupuesto, que solo se usan con una razón nueva y registrada antes de correr.
