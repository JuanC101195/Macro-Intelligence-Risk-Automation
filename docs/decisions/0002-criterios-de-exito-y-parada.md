# ADR 0002 — Criterios de éxito y de parada

- Fecha: 2026-10-11
- Estado: aceptada

## Contexto

El objetivo de largo plazo es operar con capital real propio (ADR 0001). El riesgo más grande no es técnico: es **convencerse de que existe una ventaja que no existe**. Eso pasa por sobreajuste, por mover criterios después de ver resultados o por ignorar costes.

Esta ADR fija las reglas **antes** de ver cualquier resultado. Así el sistema funciona como un laboratorio que dice la verdad, no como una confirmación de lo que queremos ver.

Expectativa realista: la mayoría de las cuentas minoristas de CFD pierden dinero, y una estrategia con indicadores públicos (EMA/RSI/MACD) en FX M15 probablemente no tiene ventaja después de costes. Si los criterios no se cumplen, **ese es un resultado válido**: el sistema habrá evitado una pérdida real.

## Reglas contra el autoengaño

1. **Criterios fijos.** Los umbrales de esta ADR no se cambian después de ver resultados. Cambiarlos requiere una ADR nueva, escrita y justificada **antes** de volver a evaluar.
2. **Hold-out intocable.** Los últimos 12 meses de datos de cada símbolo se reservan y no se usan para diseñar ni ajustar nada. Se evalúan **una sola vez**, al final. Un hold-out ya mirado queda "quemado" y no vuelve a contar como fuera de muestra.
3. **Registro de todo experimento.** Cada variante probada (parámetros, reglas, modelo) se registra con su resultado, también las que fallan. El número de variantes probadas se reporta junto a cualquier resultado.
4. **Siempre con costes.** Spread, comisión, slippage y swap en todo resultado. Sin costes no es un resultado.
5. **Sin ajustes sobre el test.** Nunca se optimiza mirando el conjunto de test ni el periodo de paper/demo.

## Puerta A — de investigación a paper trading

Se evalúa en el backtest (Fase 6) y, si hay modelo, en la validación de la Fase 8. **Todas** deben cumplirse:

| # | Criterio | Umbral |
|---|----------|--------|
| A1 | Historia | ≥ 3 años de M15 por símbolo, sin contar el hold-out |
| A2 | Muestra fuera de muestra (walk-forward) | ≥ 300 operaciones en total |
| A3 | Expectancy neta por operación (OOS, costes ×1) | > 0 |
| A4 | Profit factor OOS, costes ×1 | ≥ 1.20 |
| A5 | Profit factor OOS, costes ×1.5 | > 1.00 |
| A6 | Ventanas walk-forward con resultado neto positivo | ≥ 60 % |
| A7 | Drawdown máximo OOS con riesgo 0.25 % por operación | ≤ 10 % |
| A8 | Sin dependencia de un periodo | Quitando el mejor año, el resultado sigue > 0 |
| A9 | Estabilidad de parámetros | Las combinaciones vecinas de los parámetros elegidos también tienen expectancy > 0 (no hay un pico aislado) |
| A10 | Hold-out (evaluado una vez) | Expectancy neta > 0 y profit factor ≥ 1.10 |

## Puerta B — de paper a demo

| # | Criterio | Umbral |
|---|----------|--------|
| B1 | Duración en paper | ≥ 8 semanas |
| B2 | Estabilidad técnica | Cero errores no controlados; reinicios sin duplicados ni pérdida de estado |
| B3 | Coherencia con el backtest | Expectancy de paper dentro del rango esperado por el backtest del mismo periodo |
| B4 | Costes reales | Spread y slippage observados ≤ los del modelo de costes (si no, se recalcula la Puerta A con los reales) |

## Puerta C — de demo a dinero real

Fuera del MVP. Cumplir esta puerta **habilita a escribir** la ADR que desbloquea live, no la desbloquea automáticamente.

| # | Criterio | Umbral |
|---|----------|--------|
| C1 | Duración paper + demo | ≥ 3 meses y ≥ 100 operaciones |
| C2 | Resultado | Expectancy neta > 0 y drawdown ≤ 1.5 × drawdown máximo OOS |
| C3 | Seguridad | Circuit breaker y kill switch probados en demo; checklist de la Fase 12 completo; auditoría sin hallazgos críticos |
| C4 | Capital inicial | Monto que Juan puede perder **por completo** sin afectar su vida; riesgo 0.25 % por operación |
| C5 | Escalado | Más capital solo tras ≥ 3 meses reales cumpliendo C2; nunca para "recuperar" pérdidas |

## Criterios de parada y pivote

**Presupuesto de investigación:** como máximo **20 variantes** de una misma hipótesis se evalúan contra la Puerta A. Si ninguna pasa:

- se deja de ajustar esa hipótesis (no se buscan "más parámetros");
- se registra el resultado negativo;
- se pivota a una hipótesis distinta, en este orden sugerido: timeframe mayor (H1/H4), Crucix solo como filtro de cuándo **no** operar, otros activos, lógica distinta (reversión a la media).

**Parada en paper, demo o real:** se detienen las operaciones nuevas y se vuelve a investigación si ocurre cualquiera de estas condiciones:

- drawdown > 1.5 × drawdown máximo OOS;
- 3 meses calendario consecutivos con resultado neto negativo;
- la expectancy real cae fuera del rango esperado durante 2 meses seguidos;
- spread o slippage reales hacen que la Puerta A deje de cumplirse.

## Consecuencias

- La Fase 6 implementa estos criterios como verificaciones automáticas: el reporte de backtest muestra cada criterio A1–A10 con ✓ o ✗.
- Se crea un registro de experimentos en `research/` (local; no se sube mientras el repo sea público, ADR 0001 #14).
- La Fase 12 usa las Puertas B y C como checklist.
