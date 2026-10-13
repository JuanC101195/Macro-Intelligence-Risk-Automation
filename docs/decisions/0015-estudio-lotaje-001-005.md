# ADR 0015 — Estudio de lotaje entre 0.01 y 0.05 para `trendbo-xau-h4-channel` (informativo)

- Fecha: 2026-10-13
- Estado: aceptada (escrita **antes** de correr el estudio)
- Tipo: estudio de gestión de capital. **No** es una hipótesis nueva: no cambia entradas ni salidas, no gasta variantes del presupuesto y no cambia el veredicto de la ADR 0014.

## Contexto

Juan pidió probar la estrategia con un lote **entre 0.01 y 0.05, sin pasar de 0.05**, decidiendo cuándo subirlo. Hay que dejar dos cosas claras desde el principio:

1. **El lote no cambia la probabilidad de ganar una operación.** Solo escala cuánto se gana o se pierde, y por eso cambia el drawdown y el riesgo de ruina.
2. Subir el lote después de perder (martingala) o después de una racha está prohibido (ADR 0005). La única regla legítima para subirlo es que **haya crecido el capital**.

## Qué se mide

Se toman las operaciones de `trendbo-xau-h4-channel` desde 2004-06 hasta el último dato (investigación + hold-out ya usado), simuladas por el motor con los costes de la ADR 0006. La lista se genera con un capital muy grande (10 000 000), para que **ninguna señal** se rechace por lote mínimo: aquí es la política de lote la que decide si se opera. Cada operación se reescala con su resultado **por lote** (pnl / volumen), que ya incluye spread, slippage y swap.

**Cuentas:** estándar (0.01 lote = 1 oz) y cent (0.01 lote = 0.01 oz en USD), con capital inicial de **25, 100 y 175 USD** (ADR 0005).

**Políticas de lote (fijadas aquí):**

| Política | Regla |
|---|---|
| `fijo-0.01` | Siempre 0.01 |
| `fijo-0.05` | Siempre 0.05 |
| `proporcional` | lote = capital actual × 0.5 % ÷ pérdida hasta el stop por lote, redondeado hacia abajo a 0.01 y con tope 0.05. Si da menos de 0.01, **no se opera** (como el gestor de riesgo) |
| `escalones` | 0.01 al inicio; sube 0.01 por cada +50 % de capital sobre el inicial (×1.5 → 0.02, ×2.0 → 0.03, ×2.5 → 0.04, ×3.0 → 0.05) y baja si el capital vuelve a caer bajo el escalón. Tope 0.05 |

**Periodos:** completo (2004–2026), desde 2019 (precios del oro parecidos a los actuales) y últimos 12 meses.

**Métricas:** capital final, retorno, drawdown máximo en %, peor pérdida de una operación como % del capital, operaciones saltadas y **ruina** (capital ≤ 0 o sin margen para 0.01 lotes, con apalancamiento 1:50 del oro).

## Limitaciones

Es una reproducción de una secuencia de operaciones fija. No reproduce el circuit breaker ni los rechazos por margen del motor (salvo en la regla de ruina), y es **un solo camino histórico**: no da una probabilidad. Sirve para ver el orden de magnitud del riesgo de cada política, no para elegir la que más ganó.

## Decisión posterior

La política para paper trading y demo se elige con un criterio de riesgo, no de ganancia: drawdown máximo ≤ 10 % y sin ruina en ningún periodo y capital. Si ninguna política con lote ≥ 0.01 cumple con el capital previsto, la conclusión es que **hace falta más capital o una cuenta cent**, no subir el riesgo.
