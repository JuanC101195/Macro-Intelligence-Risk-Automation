# ADR 0020 — Oro: misma entrada de tendencia con salida 1 : 1

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** del código y de cualquier corrida)

## Contexto

Juan quiere operar con riesgo y beneficio iguales: "ganar 10 dólares o perder 10 dólares" por operación, viendo el gráfico. La ADR 0014 probó la salida por objetivo con 2R (`--exit target`, `target_r = 2`) y no pasó; la salida 1R no se probó. Con la ADR 0019 se vio que la ventaja de la entrada parece estar solo en el oro, así que esta prueba se limita al oro.

Aviso registrado: una salida 1 : 1 solo gana si la entrada acierta la dirección más del 50 % de las veces por encima de los costes. Con entradas sin ventaja da ~50 % de acierto y resultado negativo.

## Decisión

- **Entrada:** idéntica a `trendbo-xau-v001` (EMA 50/200, ruptura de 20 velas, stop inicial 2 × ATR(14)).
- **Salida:** take-profit vinculante a **1 × la distancia del stop** (`exit_mode = target`, `target_r = 1.0`); es decir stop y objetivo a 2 × ATR. Sin salida por canal.
- **Dos versiones:** `trendbo-xau-h4-target1r` y `trendbo-xau-h1-target1r`. Riesgo y límites de la ADR 0014 (0.5 %, una posición, 17 500 de capital equivalente).
- La distancia se fija en ATR y no en dólares: 10 USD de precio del oro eran ~2 ATR H4 en 2005 y ~0.4 ATR hoy; en dólares fijos la regla cambiaría de significado con el tiempo. Los "10 USD" de Juan se reflejan en el reporte como **10 USD por R** (cada operación arriesga 10 USD).
- **Evaluación:** Puerta A completa como siempre (costes ×1/×1.5/×2, ventanas de 6 meses, vecinos de A9 de la ADR 0014, A11 con 200 nulos solo si A1–A9 pasan). A10 no se evalúa (hold-out usado).
- **Reporte adicional:** acierto, operaciones por semana y, con 10 USD por operación: resultado medio por semana, peor semana, peor mes y peor racha en dólares.
- Son 2 pruebas nuevas.

## Riesgo de capital (independiente del resultado)

Arriesgar 10 USD por operación con 25–175 USD (ADR 0005) es 6–40 % del capital por operación; con rachas de 4–5 pérdidas, normales en cualquier estrategia, la cuenta se pierde. Con el 0.5 % de la política de riesgo, 10 USD por operación exige ~2 000 USD. Ningún resultado de esta ADR cambia la política de riesgo.

## Resultado — 2026-10-15 (2004-06 → 2025-10, sin A11)

| | Oro H4 1 : 1 | Oro H1 1 : 1 |
|---|---|---|
| Operaciones (por semana) | 1 146 (1.0) | 3 965 (3.6) |
| Acierto | 53 % | 50.2 % |
| PF costes ×1 / ×1.5 / ×2 | 1.08 / 1.07 / 1.05 | 0.96 / 0.89 / 0.83 |
| Drawdown máx. (0.5 %) | 11.5 % | 38.8 % |
| Con 10 USD por operación: neto 21 años | +460 USD | −749 USD |
| Semana media / peor semana / peor mes | +0.42 / −28 / −33 USD | −0.67 / −43 / −95 USD |
| Peor caída acumulada | −273 USD | −1 004 USD |
| Criterios fallados | A4, A6, A7 | A3–A9 |

- **Ninguna pasa la Puerta A.** A11 no se corre.
- H1 1 : 1 acierta 50.2 %: la entrada no tiene ventaja en H1. H4 1 : 1 acierta 53 %: hay un poco de ventaja en la entrada, pero cortar la ganancia en 1R se come la mayor parte (PF 1.08 frente a 1.34 de la salida por canal, que deja correr las ganancias).
- Se sigue con `trendbo-xau-h4-channel` sin cambios.

## Consecuencias

- Código: opción `--target-r` en `backtest trend` (valores pre-registrados: 2.0 de la ADR 0014 y 1.0 de esta ADR) y métricas en dólares por R.
