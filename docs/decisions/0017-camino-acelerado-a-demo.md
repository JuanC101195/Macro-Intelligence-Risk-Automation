# ADR 0017 — Camino acelerado de paper a demo para `trendbo-xau-h4-channel`

- Fecha: 2026-10-14
- Estado: aceptada (escrita **antes** de medir el spread histórico y antes de la repetición)
- Modifica: ADR 0002 (Puerta B, solo B1 y B4 y solo para esta regla), ADR 0016

## Contexto

La Puerta B pide 8 semanas en paper (B1). Con unas 23 señales al año, esas 8 semanas dan 3 a 5 operaciones. El tiempo sirve para probar la tubería y medir costes, no la ventaja de la estrategia. Juan no quiere esperar hasta diciembre para la demo.

La demo usa dinero ficticio del bróker: adelantarla no arriesga dinero. Lo que la Puerta B protege es que a la demo llegue un sistema sin errores y con costes conocidos. Eso se puede verificar de otra forma.

## Decisión

Para `trendbo-xau-h4-channel`, B1 y B4 se reemplazan por:

- **B1' — Repetición y vivo corto:**
  1. **Repetición:** el `PaperTrader` procesa una por una las velas H4 reales de MT5 de los **últimos 12 meses**, como si fuera en vivo, con un proceso nuevo cada cierto número de velas para probar los reinicios. Debe dar cero errores, ningún duplicado y `paper report` con paridad `ok` (cero diferencias sin explicar).
  2. **Vivo:** al menos **10 días hábiles** de `paper tick` en vivo sin errores no controlados (`stale_data` no cuenta como error).
- **B4' — Spread histórico real:** con el historial de ticks de MT5 (MetaQuotes-Demo), se toma el spread del **primer tick después de cada cierre H4** de los últimos 6 meses.
  - Si la **mediana es ≤ 30 puntos**, B4' se cumple.
  - Si es **mayor**, se vuelve a correr la Puerta A (A1–A9 y A11; A10 ya está usada) con el spread medido (mediana redondeada hacia arriba). Si la regla deja de pasar, **no va a demo**.
  - Ese umbral y ese procedimiento no se cambian después de ver el número.
- **B2 y B3** no cambian.
- **Demo:** necesita el ejecutor demo de la Fase 11 (con su verificación de cuenta demo y de duplicados), `ALLOW_DEMO_ORDERS=true` y la contraseña de operación de la cuenta **demo** en `.env`. El riesgo, el lote y los límites son los mismos del paper.
- **Dinero real: sin cambios.** La Puerta C sigue igual. Una cuenta real solo se abre con una ADR propia, y nunca la habilita ninguna de estas pruebas.

## Consecuencias

- La demo puede empezar en 2–3 semanas en lugar de 8.
- La repetición sobre velas pasadas no mide el llenado al tick en vivo. Eso lo cubren los 10 días en vivo y después la propia demo.
- El paper en vivo sigue corriendo en paralelo con la demo, como referencia.

## Adenda 1 (2026-10-14, antes de volver a medir)

La primera medición de B4' **no es válida**. El script pasaba a `copy_ticks_range` una hora sin zona horaria, y MT5 la interpretó como hora local del PC (UTC−5): los ticks se leyeron 5 horas después de cada cierre. Los cierres de las 17:00 UTC caían en la reapertura tras la pausa diaria del oro, con spreads de hasta ~149 USD, y la mediana salió en 27 puntos.

Se verificó con las últimas velas: con la hora en UTC explícito, el bid del primer tick coincide con el cierre de la vela (4083.48 contra 4083.47 el 2026-10-14 a las 17:00 UTC). Se corrige el script y se vuelve a medir una vez, con el mismo umbral y el mismo procedimiento. El resultado inválido no se usa.

## Resultado B4' (2026-10-14, medición válida)

769 cierres H4 en 6 meses, 641 con tick en los 5 minutos siguientes. Los 128 sin tick son los cierres de las 21:00 UTC (pausa diaria y cierre del viernes). Spread del primer tick: **mediana 22 puntos**, p75 34.5, p95 51 y máximo 69. Mediana por hora de cierre (UTC): 01 h → 28, 05 h → 24.5, 09 h → 21.5, 13 h → 23 y 17 h → 19.5. **B4' se cumple** (22 ≤ 30): el modelo de costes del backtest es conservador.

Hallazgo: si una señal cierra a las 21:00 UTC solo se puede operar en la reapertura. El paper se corrigió (ADR 0016, adenda 1).

## Resultado B1' parte 1: repetición de 12 meses (2026-10-14)

Script `research/lab/paper_replay.py`, de 2025-10-15 a 2026-10-14: 1 547 velas H4 reales procesadas una por una, con un proceso nuevo cada 50 velas (30 reinicios).

- **Primera corrida:** paridad `ok`, pero con 54 `stale_data` falsos (fines de semana) y 1 señal perdida. Se corrigió el chequeo de frescura (ADR 0016, adenda 2) **antes** de repetir.
- **Segunda corrida:** 1 546 velas procesadas, **0 errores, 0 `stale_data`, 0 duplicados y paridad `ok`** (20 operaciones, 0 diferencias sin explicar). 9 señales rechazadas por lote mínimo, igual que en el motor.
- Las diferencias de precio frente al motor son de centavos (el motor suma 5 puntos de slippage; la repetición llena al tick sin slippage). La excepción son las salidas por canal tras un hueco: el paper sale al precio de reapertura (el 2026-08-07, 4340.87 contra 4350.05 al cierre en el motor). Eso es lo que pasaría en realidad.
- **La parte 1 de B1' se cumple.** Falta la parte 2: 10 días hábiles en vivo sin errores, desde el 2026-10-15.
- El resultado económico de la repetición (+7.7 % en el periodo) no es evidencia nueva: es el hold-out ya usado (ADR 0014).
