# ADR 0023 — Cambio de mes: prueba de confirmación en índices no vistos

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** de descargar y mirar los datos de estos índices)

## Contexto

Juan pidió iterar sobre el cambio de mes para "encontrar alguna variable que lo haga pasar". Buscar variables hasta que una pase es sobreajuste (con 20 intentos, uno pasa por azar). Además, la adenda 2 de la ADR 0022 corrigió un bug de fechas: con la regla original (Lakonishok y Smidt), US500 + US30 dan PF 0.86 en 2012–2025; el "casi pasa" anterior venía de una regla corrida un día por el bug.

La única iteración que no se puede amañar es probar **la misma regla** en mercados que nunca miramos. Si el efecto es real (como dice la literatura internacional sobre el cambio de mes), debe aparecer ahí.

## Decisión

- **Universo por regla, no a dedo:** todos los símbolos de la carpeta `Indexes\` de MetaQuotes-Demo con historia D1 desde 2018-10-15 o antes (≥ 8 años), excepto US500, US30 y USTEC (ya vistos). Con la consulta del 2026-10-15: DE40, IT40, NETH25, SWI20, CHINA50, MIDDE50, TECHDE30, US2000 (la lista final se toma de la misma regla al descargar; si aparece otro símbolo que la cumpla, entra).
- **Regla única, sin variantes:** `tom-v1` exactamente como en la ADR 0022 (comprar al cierre del penúltimo día hábil del mes, vender al cierre del tercer día hábil del siguiente), con la fecha de sesión en hora del servidor (adenda 2 de la ADR 0022). Stop 2 × ATR(14) diario, riesgo 0.25 %.
- **Costes por símbolo:** spread = el spread actual de MT5 de ese símbolo (consulta del 2026-10-15), deslizamiento = 25 % del spread por lado; financiación de compra = tasa de la moneda del índice (EUR, CHF o USD, FRED) + 1 % / 360 por noche.
- Periodo: hasta 2025-10-01 (misma fecha de corte que la ADR 0022).
- **Veredicto de la canasta completa (todo o nada):** Puerta A A1–A9 y, si pasan, A11 con 200 nulos (día de entrada al azar dentro del mes, misma duración). A10 no se evalúa.
- **Si no pasa, la línea del cambio de mes se cierra** (no se prueban otras fechas, filtros ni subconjuntos).

## Consecuencias

- Descarga D1 de esos índices (local). El script `calendar_effects.py` gana un modo `--tom-intl`.
