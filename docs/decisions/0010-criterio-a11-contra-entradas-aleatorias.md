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

## Adenda 2026-10-12 — calibración con entradas ejecutadas (antes de re-correr)

Al aplicar A11 a las cinco primeras hipótesis se vio que las versiones aleatorias operan **mucho más** que la estrategia (ruptura H4: 1 141 operaciones reales frente a 1 658–1 836 aleatorias; ruptura D1: 220 frente a 318–395). Causa: la probabilidad se calculó con **señales** / llamadas sin posición, y la ruptura repite la señal en cada vela mientras el precio sigue fuera del canal; el gestor de riesgo rechaza la mayoría (9 466 señales para 1 141 operaciones). Las entradas aleatorias, repartidas en el tiempo, se rechazan menos. Con más operaciones el profit factor nulo varía menos, el percentil 95 baja y el criterio queda **sesgado a favor de pasar**. Por eso esos cinco resultados no se usan.

Corrección (antes de cualquier nueva corrida):

1. *p* = **operaciones ejecutadas** del instrumento en la corrida base / llamadas sin posición.
2. La proporción de LONG y los pares (stop, TP) en ATR se toman solo de las señales que se convirtieron en operación.
3. Todo lo demás del modelo nulo y del criterio sigue igual. Se reporta el rango de operaciones de los nulos junto a las reales; si la mediana nula queda fuera de ±20 % de las reales, se anota en el resultado.

Además: la corrida base de `baseline-v001-h4` no reproduce el digest registrado a las 03:45 UTC del 2026-10-12 (PF 0.965 frente a 0.970). Con el código de `main`, sin A11, sale el **mismo** digest nuevo (`f14bc57…`), así que la diferencia viene de cambios posteriores al registro (especificaciones por instrumento y costes por símbolo, commit `9daeac0`, que cambió el fingerprint de configuración), no de A11. Las demás corridas base reproducen su registro.

## Resultado de la aplicación retroactiva (2026-10-12) — ninguna supera al azar

Con el nulo calibrado de la adenda, 200 versiones por hipótesis, configuración base, costes ×1 (los valores concretos quedan en los reportes locales):

| # | Hipótesis | ¿Supera el percentil 95? |
|---|---|---|
| 1 | baseline M15 | no |
| 2 | baseline H1 | no |
| 3 | baseline H4 | no |
| 4 | baseline H1 + filtro macro *block* | no |
| 5 | baseline H1 + filtro macro *confirm* | no |
| 6 | carry D1 | no |
| 7 | ruptura D1 | no |
| 9 | ruptura H4 (control) | no |
| 10 | ruptura H4 + regímenes GMM | no (con el nulo sin calibrar "pasaba" por 0.0003: era el sesgo descrito en la adenda) |

Ninguna estrategia probada hasta hoy tiene entradas mejores que el azar con su misma gestión. Las corridas base de ruptura, carry y regímenes reproducen su digest registrado. Las cuatro de baseline (M15, H1, H1 *block*, H1 *confirm*) no lo reproducen por la misma causa que H4: los costes por símbolo cambiaron después del registro (`9daeac0`), y en H4 se comprobó con el código de `main` que A11 no altera la corrida.

## Consecuencias

- Toda hipótesis nueva paga ~200 corridas extra de backtest (en H4, ~13 min con todos los núcleos).
- Una estrategia cuyo resultado se explica por la gestión de la salida o por la deriva del periodo deja de poder pasar la Puerta A.
- El reporte de backtest muestra A11 junto a A1–A10.
