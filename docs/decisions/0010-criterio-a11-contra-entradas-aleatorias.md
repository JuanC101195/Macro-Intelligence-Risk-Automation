# ADR 0010 — Criterio A11 de la Puerta A: superar a las entradas aleatorias

- Fecha: 2026-10-12
- Estado: aceptada (escrita **antes** de implementar el criterio o de ejecutar cualquier corrida con él)

## Contexto

La ADR 0009 mostró que una mejora frente a un control puede ser ruido: un filtro aleatorio subió el profit factor de la ruptura H4 casi tanto como el filtro GMM. Los criterios A1–A10 miden si el resultado es positivo, estable y robusto a costes, pero ninguno pregunta si las **reglas de entrada** aportan algo frente a entrar al azar con la misma gestión de la operación. Con stops amplios, take-profit lejano y salidas por canal, buena parte del resultado puede venir de la lógica de salida, del lotaje o de la tendencia del periodo, no de la señal.

La regla 1 de la ADR 0002 permite añadir criterios con una ADR nueva escrita **antes** de volver a evaluar. Esta es esa ADR.

## Decisión

### Criterio A11

| # | Criterio | Umbral |
|---|----------|--------|
| A11 | Las entradas superan al azar | Profit factor OOS (costes ×1) **>** percentil 95 del profit factor de **200** versiones con entradas aleatorias |

Si A11 no se evalúa (corrida rápida, hold-out o estrategia sin modelo nulo), queda **pendiente** y la Puerta A **no** puede darse por pasada.

### Modelo nulo (versión con entradas aleatorias)

Se construye por igual para cualquier estrategia de una sola pata que use el motor propio (`Backtest`), envolviendo su función de decisión:

1. **Perfil observado** (de la corrida base, costes ×1, sin cambiar su resultado): por instrumento, el número de llamadas a la estrategia estando **sin posición** y sin circuit breaker, el número de señales de entrada emitidas, la proporción de LONG, y para cada señal la distancia del stop y del take-profit a la entrada medida en **ATR(14) de la vela de la señal**.
2. **Entradas aleatorias:** en cada llamada sin posición y sin circuit breaker, con ATR(14) disponible, se emite una entrada con probabilidad *p* = señales / llamadas sin posición de ese instrumento. La dirección es LONG con la proporción observada. Stop y take-profit se toman de un par (stop, TP) elegido al azar entre los observados de ese instrumento, escalado por el ATR(14) actual. Un take-profit de SHORT que quedaría ≤ 0 se fija en el 10 % del precio de entrada (regla de la ADR 0006).
3. **Todo lo demás igual:** misma salida por señal (`exit_check`) de la estrategia, mismo gestor de riesgo y lotaje, mismos límites, costes, financiación, capital, periodo y datos.
4. **Semillas 0–199**, un generador por (semilla, instrumento), así que cada versión es reproducible.

Se reporta además: percentil del profit factor y de la expectancy observados, p-valor `(1 + #nulos ≥ observado) / (N + 1)`, y el rango de operaciones de los nulos frente a las observadas.

### Alcance

- **Estrategias de dos patas** (pares, ADR 0007, que usa su propio motor): A11 queda pendiente hasta que una ADR propia defina su modelo nulo.
- **Hipótesis que son un filtro sobre una base** (macro, regímenes): además de A11, su ADR debe pre-registrar un nulo de **filtro** aleatorio con la misma tasa de bloqueo, como la prueba 2 de la ADR 0009.
- Se ejecuta con el motor propio (no vectorbt; ADR 0009 regla 3), en paralelo por procesos. Las corridas nulas **no cuentan** como variantes del presupuesto de 20 (no son hipótesis nuevas).
- No se usa para ajustar nada: si una hipótesis no pasa A11, no se buscan reglas de entrada "que sí la pasen" dentro de la misma hipótesis.

### Aplicación retroactiva (solo informativa)

A11 se aplica a las hipótesis 1–7, 9 y 10 con su configuración base registrada, para saber cuáles tenían entradas mejores que el azar. **No cambia ningún veredicto** (ninguna pasó la Puerta A) ni reabre hipótesis abandonadas. Antes de usar cada resultado, la corrida base debe reproducir el `trades_digest` registrado en `research/experiments.jsonl`; si no coincide, se investiga antes de seguir. La hipótesis 8 (pares) queda fuera por el alcance.

## Consecuencias

- Toda hipótesis nueva paga ~200 corridas extra de backtest (en H4, ~13 min con todos los núcleos).
- Una estrategia cuyo resultado se explica por la gestión de la salida o por la deriva del periodo deja de poder pasar la Puerta A.
- El reporte de backtest muestra A11 junto a A1–A10.
