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

## Consecuencias

- Código: opción `--target-r` en `backtest trend` (valores pre-registrados: 2.0 de la ADR 0014 y 1.0 de esta ADR) y métricas en dólares por R.
