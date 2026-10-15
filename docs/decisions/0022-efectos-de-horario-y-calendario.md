# ADR 0022 — Efectos de horario y calendario publicados: oro noche/día y cambio de mes

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** del código y de cualquier corrida)

## Contexto

Tras 19 hipótesis de análisis técnico (solo una pasa), Juan pidió buscar estrategias publicadas que se puedan replicar y validar. Se eligen dos efectos documentados en literatura académica, con reglas fijadas por los estudios (no por nuestros datos):

1. **Oro noche/día** — Blose, Gondhalekar y Kort (2018, *Journal of Economics and Finance*): en futuros COMEX, fixing de Londres, mineras y fondos de oro, el rendimiento de **noche** es positivo y el de **día** negativo, también con costes.
2. **Cambio de mes (TOM)** — Lakonishok y Smidt (1988): el índice sube del último día hábil del mes al tercero del siguiente; Carchano y Pardo (2011) lo hallan como el único efecto de calendario persistente en futuros del S&P 500 (de 188 probados). Evidencia posterior mixta: se adelantó y se debilitó.

Se descarta por ahora el **pre-FOMC** (Lucca y Moench 2015): la evidencia muestra que cayó de ~0.5 % a ~0.1 % por reunión tras 2011, y reconstruir el calendario de reuniones 2004–2025 no compensa.

Advertencia (McLean y Pontiff 2016): tras publicarse, las anomalías rinden ~la mitad. Se reporta aparte el periodo posterior a la publicación.

## Decisión

### Prueba 1 — oro noche/día (XAUUSD M1, 2009 → 2026-10-15)

- **Día** = 08:20 → 13:30 hora de Nueva York (sesión regular COMEX); **noche** = 13:30 → 08:20 del siguiente día hábil. Precio de la vela M1 de esas horas (apertura); compra al ask, venta al bid; deslizamiento 0.05 USD por lado; comisión 0 (spread incluido en el bid/ask).
- **`gold-night-long`**: comprar a las 13:30 y vender a las 08:20 del siguiente día hábil (viernes → lunes incluido). Swap de compra: (tasa USD + 1 %) / 360 por **noche de calendario** cruzada (fin de semana = 3).
- **`gold-day-short`**: vender a las 08:20 y recomprar a las 13:30 del mismo día. Sin swap.
- Stop de protección a 2 × ATR(14) diario (no está en el estudio; lo exige la política de riesgo); riesgo 0.25 % por operación según ese stop.
- A9 (vecinos): ventanas desplazadas ±1 h (07:20/09:20 y 12:30/14:30).

### Prueba 2 — cambio de mes (US500 y US30, D1, 2004 → 2025-10)

- **`tom-v1`** (Lakonishok y Smidt): comprar al cierre del **penúltimo** día hábil del mes y vender al cierre del **tercer** día hábil del mes siguiente. Canasta US500 + US30, todo o nada.
- Costes por instrumento de la ADR 0006 y financiación de compra (USD + 1 %) por noche de calendario. Stop 2 × ATR(14) diario; riesgo 0.25 %.
- A9 (vecinos): entrar un día antes o después; salir al segundo o cuarto día hábil.

### Evaluación (igual para ambas)

- Las reglas vienen de la literatura: **todo el periodo es fuera de muestra**. Puerta A A1–A9 (ventanas de 6 meses; costes ×1, ×1.5, ×2). A10 no se evalúa (hold-out usado).
- **A11, 200 nulos:** misma duración y dirección, con hora de entrada al azar dentro del día (oro) o día de entrada al azar dentro del mes (TOM). Solo si A1–A9 pasan.
- Informativo: resultado antes y después de la publicación (oro: desde 2018; TOM: todo es posterior a 1988), operaciones por semana y vista con 10 USD por operación.
- Son 3 pruebas (`gold-night-long`, `gold-day-short`, `tom-v1`).

## Adenda 1 — 2026-10-15 (antes del código y de cualquier corrida)

El spread del oro en las velas M1 de MetaQuotes es 0 en 2009–2010 y poco realista en otros tramos (mismo problema que la ADR 0006 vio en FX). Para el oro se usa **el mayor** entre el spread de la vela y el fijo de la ADR 0006 (30 puntos = 0.30 USD), más 0.05 USD de deslizamiento por lado. Para US500/US30 se usan los fijos de la ADR 0006 (spread 0.50 / 2.00 y deslizamiento 0.20 / 1.00 puntos de índice por lado). Ninguna regla de entrada o salida cambia.

## Resultado — 2026-10-15

Auditoría del oro: 20 de 20 operaciones idénticas a la versión vela a vela.

| | Oro noche (compra) | Oro día (venta) | Cambio de mes US500+US30 |
|---|---|---|---|
| Periodo / operaciones | 2009-01 → 2026-10 / 4 395 | 2009-01 → 2026-10 / 4 416 | 2012-08 → 2025-10 / 310 |
| Acierto | 50.4 % | 46.5 % | 55.5 % |
| PF costes ×1 / ×1.5 / ×2 | 1.00 / 0.92 / 0.85 | 0.87 / 0.81 / 0.75 | 1.13 / 1.05 / 0.99 |
| Drawdown máx. (0.25 %) | 11.3 % | 14.3 % | 2.4 % |
| Antes / después de la publicación | PF 0.89 (<2018) / 1.12 (≥2018) | 0.82 / 0.93 | (todo posterior) |
| Con 10 USD por operación | −10 USD | −579 USD | +100 USD (+0.64 USD/semana con operación) |
| Criterios fallados | A3–A9 | A3–A9 | A4, A6, A9 |

- **Ninguna pasa la Puerta A.** A11 no se corre.
- El efecto noche/día del oro no aparece en nuestros datos con costes (PF 1.00); la venta de día pierde todos los periodos.
- El cambio de mes es positivo (PF 1.13, drawdown muy bajo), pero no llega a 1.20, solo el 58 % de los semestres son positivos y dos vecinos (entrar un día antes, salir un día antes) son negativos: la ventaja es pequeña y frágil. **No se afina.** Queda anotado como el efecto publicado más cercano a pasar.
- Hipótesis 20, 21 y 22: descartadas.

## Adenda 2 — 2026-10-15 (bug en el cambio de mes, encontrado después del resultado)

Las velas D1 de MetaQuotes vienen etiquetadas a las 21:00 UTC del día **anterior** (medianoche del servidor UTC+3). El script tomaba la fecha en UTC, así que cada sesión quedaba fechada un día antes: el primer día hábil de cada mes contaba como último del mes anterior. La regla realmente probada fue "entrar al cierre del día −3 y salir al del día +2", no la pre-registrada. Corrección: fecha de sesión = (hora + 3 h). Se re-ejecuta **solo `tom-v1` con la regla original**; el resultado anterior queda arriba como registro. Las pruebas del oro no cambian (usan M1 en hora de Nueva York).

## Consecuencias

- Script de laboratorio `research/lab/calendar_effects.py` con auditoría de 20 operaciones. Si algo pasa, se porta a `src/` antes de paper.
