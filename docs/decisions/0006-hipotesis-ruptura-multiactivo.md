# ADR 0006 — Hipótesis H-BREAKOUT-1: ruptura de canal (trend following) multi-activo

- Fecha: 2026-10-12
- Estado: aceptada (pre-registro: escrita **antes** de ejecutar cualquier prueba)

## Contexto

Seis hipótesis anteriores (patrones de precio en FX, filtro macro, carry) no pasaron la Puerta A. El seguimiento de tendencia por ruptura de canal (reglas tipo Donchian / "Turtle") es la base de los fondos *managed futures* y tiene décadas de evidencia académica, **sobre todo cuando se diversifica entre clases de activos** (materias primas, índices, divisas). Los robots de oro que se venden en MQL5 son mayoritariamente de ruptura, pero sus propios resultados en vivo publicados son negativos; aquí se prueba la versión pública y simple, sin optimizar.

Prior honesto: **moderado** a largo plazo en carteras diversificadas; la evidencia es más débil en la última década y con solo 3 posiciones simultáneas.

## Universo y datos (D1, MetaQuotes-Demo)

| Clase | Instrumentos | Historia D1 |
|-------|--------------|-------------|
| Metales | XAUUSD, XAGUSD | 2004 / 2008 |
| Índices EE. UU. | US500, US30, USTEC | desde 2012 aprox. |
| Divisas | EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF | 2010 |

Todos con beneficio en USD (o USDXXX convertido). El periodo de investigación empieza cuando **todos** tienen datos; hold-out de 12 meses no se usa.

## Reglas (versión `breakout-v001`)

1. **Entrada LONG** al cierre de una vela D1 cuyo cierre supera el **máximo de las 55 velas anteriores**; **SHORT** si cierra por debajo del **mínimo de las 55 anteriores**. Ejecución en la apertura siguiente.
2. **Salida** al cierre: LONG si el cierre cae por debajo del mínimo de las **20** velas anteriores; SHORT si supera el máximo de las 20 anteriores.
3. **Stop-loss** a 2 × ATR(20) desde la entrada; take-profit obligatorio del contrato a 20 × ATR (no vinculante).
4. Máximo **3 posiciones** a la vez (techo de `risk-policy.md`); si hay más señales que huecos, entran por orden de llegada (orden alfabético dentro de la misma vela). Una posición por instrumento.
5. Riesgo 0.25 % del capital hasta el stop por posición, con el gestor de riesgo estándar.

## Capital, costes y financiación

- Capital inicial **17 500** (equivalente cent de ≈ 700 000 COP, ADR 0005).
- Especificaciones de contrato tomadas de MT5: XAUUSD 100 oz (punto 0.01, lote mínimo 0.01), XAGUSD 5 000 oz (punto 0.001), US500/US30/USTEC 1 unidad (punto 0.01, lote mínimo 0.1); FX como antes.
- Spreads fijos (puntos): XAUUSD 30, XAGUSD 30, US500 50, US30 200, USTEC 150; FX como en la ADR 0004. Slippage por operación (puntos): XAUUSD 5, XAGUSD 5, US500 20, US30 100, USTEC 50; FX 2.
- Límite de spread del gestor de riesgo desactivado para esta prueba (spreads fijos y de distinta escala por instrumento).
- Financiación diaria: FX con el diferencial de tasas − 1 % (como la ADR 0004); metales e índices: LONG paga tasa USD + 1 %, SHORT paga 1 % (no se acredita nada).
- La exposición por divisa solo se controla en pares de 6 letras (FX y metales); los índices quedan limitados por el máximo de 3 posiciones.

## Variantes vecinas (A9, fijadas aquí)

Entrada 40 / 70 velas; salida 15 / 30 velas; stop 1.5 / 2.5 × ATR.

## Adenda 2026-10-12 — desviación de datos (registrada antes de ejecutar)

Al descargar, `USTEC` solo tiene historia D1 desde **2022-07** en MetaQuotes-Demo. Como el periodo de investigación empieza cuando todos los instrumentos tienen datos, incluirlo recortaría la prueba a ~3 años. Se **excluye USTEC**; el universo queda en 11 instrumentos (XAUUSD, XAGUSD, US500, US30 y los 7 pares FX), con datos comunes desde 2012-08. Ninguna regla cambia.

## Criterio de éxito

Puerta A de la ADR 0002 sin cambios. Si falla, se descarta `breakout-v001` y la línea de investigación se pausa hasta tener más historia macro (Crucix) o una idea con fundamento distinto, priorizando la Fase 7.
