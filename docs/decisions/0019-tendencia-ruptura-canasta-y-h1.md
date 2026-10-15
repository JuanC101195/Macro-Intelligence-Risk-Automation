# ADR 0019 — La estrategia de tendencia del oro, congelada, en una canasta de activos y en oro H1

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** de escribir el código y de cualquier corrida)

## Contexto

`trendbo-xau-h4-channel` (ADR 0014) es la única versión que ha pasado la Puerta A, pero da unas 25–30 operaciones al año en un solo activo. Con ese ritmo, la Puerta C (≥ 100 operaciones en demo) tardaría años y una racha mala dura meses. Juan pide muchas más operaciones por semana y un resultado semanal más estable.

La forma legítima de tener más operaciones sin "afinar" es comprobar si la **misma ventaja** aparece en otros mercados: si comprar rupturas a favor de la tendencia funciona en el oro por una razón de fondo (los mercados tienden a seguir tendencias), también debería verse en otros activos. Si solo funciona en el oro, lo del oro probablemente fue suerte.

Expectativa honesta (ADR 0005): una cartera de tendencia realista rinde 10–25 % al año con semanas negativas frecuentes; más activos dan más operaciones y una curva más pareja, no una rentabilidad semanal alta. La hipótesis 7 (Donchian 55/20 en D1 sobre esta canasta, ADR 0006) no pasó, así que el previo es moderado.

## Decisión

### Reglas: idénticas a `trendbo-xau-h4-channel`, sin tocar nada

EMA 50/200 como filtro, entrada por ruptura de las 20 velas previas, stop inicial 2 × ATR(14), salida por el canal opuesto de 10 velas. Ningún parámetro se cambia ni se elige por activo.

### Prueba 1 — canasta H4 (`trendbo-basket-h4-channel`)

- **Universo fijo (el de la ADR 0006):** XAUUSD, XAGUSD, US500, US30, EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF. USTEC queda fuera por historia corta (misma razón que en la ADR 0006).
- Periodo: desde que todos tienen datos H4 hasta el inicio del hold-out (excluido por código).
- **Riesgo:** 0.25 % por operación; máximo **3 posiciones** a la vez (techo de `risk-policy.md`), una por instrumento; si hay más señales que huecos, entran por orden de llegada. Exposición por divisa como en la ADR 0006. Costes, spreads y financiación por instrumento como en la ADR 0006.
- **Todo o nada:** el veredicto es de la canasta completa. El resultado por instrumento se reporta solo como información; **no** se permite quitar después los activos que salgan mal (sería elegir a posteriori).

### Prueba 2 — oro en H1 (`trendbo-xau-h1-channel`)

Las mismas reglas en XAUUSD H1, con el riesgo y los límites de la ADR 0014 (0.5 %, una posición). Mide si bajar de marco temporal da más operaciones sin perder la ventaja.

### Evaluación

- Puerta A completa con la maquinaria de siempre (`runner.evaluate_suite`): costes ×1, ×1.5 y ×2; ventanas walk-forward de 6 meses; A9 con los mismos vecinos de la ADR 0014 (EMA 40/160 y 60/240, entrada 15 y 25, stop 1.5 y 2.5 ATR); **A11 con 200 versiones de entradas aleatorias**.
- **A10 no se evalúa** (hold-out ya usado, `holdout_used.json`): si una prueba pasa A1–A9 y A11, se reporta como "pasa sin hold-out".
- Se reportan además: operaciones por semana (media y mediana), % de semanas positivas, peor semana y peor mes, y operaciones rechazadas por el límite de 3 posiciones.
- Son 2 pruebas nuevas (los vecinos de A9 y los nulos de A11 no cuentan como variantes).

### Qué se hace con el resultado

- **Canasta pasa:** se convierte en la candidata principal para el paper trading en lugar del oro solo (ADR propia para el cambio).
- **Solo H1 pasa:** candidata adicional en el oro; misma regla.
- **Ninguna pasa:** se sigue con el oro H4 tal como está; la ventaja queda marcada como posiblemente específica del oro (más débil de lo que parecía).

## Consecuencias

- Código: generalizar `trend_suite` a varios instrumentos y límites configurables, y un comando `backtest trend-basket`; la lógica de la estrategia no cambia.
- A11 en H4 con 11 instrumentos puede tardar varias horas; se corre en segundo plano.
