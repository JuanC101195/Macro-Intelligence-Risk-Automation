# ADR 0007 — Hipótesis H-PAIRS-1: arbitraje estadístico AUDUSD–NZDUSD

- Fecha: 2026-10-12
- Estado: aceptada (pre-registro: escrita **antes** de escribir código o ejecutar cualquier prueba)

## Contexto

Siete hipótesis anteriores (patrones de tendencia en tres timeframes, filtro macro, carry y ruptura multi-activo) no pasaron la Puerta A. Todas eran apuestas **direccionales**. Esta es la primera de **valor relativo**: Australia y Nueva Zelanda tienen economías muy parecidas (exportadoras de materias primas, ligadas a China, con ciclos de tasas correlacionados), así que el diferencial entre AUD y NZD debería volver a su media aunque ambas monedas se muevan juntas frente al USD.

Prior honesto: **bajo a moderado**. La relación AUD/NZD es una de las más citadas en la literatura de *pairs trading* en divisas, pero es conocida (poca ventaja residual), su cointegración se ha roto por periodos largos (divergencia de tasas RBA/RBNZ) y los costes de dos patas se comen buena parte de un diferencial pequeño.

## Datos

- AUDUSD y NZDUSD en **H1**, MetaQuotes-Demo, desde 2010-09 (se descargan con hash, como el resto; locales).
- Se elige H1 y no D1 porque en D1 la regla generaría del orden de 10 operaciones por año: no podría alcanzar el mínimo de 300 operaciones de la A2 en ningún caso.
- Periodo de investigación: desde que ambos tengan datos, más el periodo de calentamiento (ventana de estimación); hold-out de 12 meses no se usa.
- Ambos cotizan en USD: el P&L de cada pata ya está en USD, sin conversión.

## Reglas (versión `pairs-v001`)

Todo se calcula al cierre de cada vela H1 con **solo datos pasados** (walk-forward implícito: las estimaciones se rehacen con ventana móvil).

1. **Relación de cobertura:** β = pendiente de la regresión OLS de ln(AUDUSD) sobre ln(NZDUSD) en las **últimas 1 000 velas H1** (≈ 2 meses). Se reestima cada 24 velas.
2. **Diferencial:** s = ln(AUDUSD) − β · ln(NZDUSD). **Z-score:** z = (s − media) / desviación, con media y desviación de las **últimas 240 velas** (≈ 10 días).
3. **Filtro de cointegración:** solo se abren operaciones nuevas si la prueba de Engle-Granger (ADF sobre los residuos de la regresión del punto 1) da **p < 0.05**. No afecta a las posiciones abiertas.
4. **Entrada** (ejecución en la apertura de la vela siguiente, las dos patas a la vez):
   - z ≥ +2 → diferencial caro: **SHORT AUDUSD + LONG NZDUSD**.
   - z ≤ −2 → diferencial barato: **LONG AUDUSD + SHORT NZDUSD**.
5. **Salida** de las dos patas a la vez cuando ocurra lo primero:
   - z cruza 0 (reversión completa);
   - |z| ≥ 4 (stop del diferencial);
   - han pasado **120 velas** (≈ 5 días) desde la entrada (stop por tiempo).
6. **Un solo par abierto a la vez** (= 2 posiciones, dentro del techo de 3 de `risk-policy.md`).

## Dimensionamiento y riesgo

- Nocional de la pata NZD = β × nocional de la pata AUD (cobertura en valor). Lotes redondeados al paso de 0.01; si alguna pata queda por debajo del mínimo, no se opera.
- Riesgo objetivo **0.25 % del capital por par**, medido como la pérdida estimada si |z| pasa de 2 a 4 (con la desviación del diferencial en el momento de entrar).
- Cada pata lleva un **stop-loss de protección** a 4 × ATR(20) H1 (contrato del gestor de riesgo; pensado para no tocarse en condiciones normales) y el take-profit contractual no vinculante a 8 × ATR. Si el stop de una pata se toca, se cierra también la otra en la apertura siguiente.
- Ambas patas pasan por el `DefaultRiskEngine`; si rechaza una, no se abre ninguna (todo o nada). La exposición neta al USD es casi cero (una pata compra USD y la otra lo vende), así que el límite de exposición por divisa no debería bloquear.

## Capital, costes y financiación

- Capital inicial **17 500** (equivalente cent, ADR 0005).
- Spreads fijos y slippage de la ADR 0004 para AUDUSD y NZDUSD, **en cada pata**; costes ×1 / ×1.5 / ×2 como siempre.
- Swap diario de cada pata con el diferencial de tasas FRED − 1 % (como la ADR 0004). Las posiciones duran pocos días, así que pesa poco.

## Conteo para la Puerta A

- **Una operación = un par completo** (entrada y salida de las dos patas). Contar cada pata por separado duplicaría la muestra de la A2 de forma artificial.
- Expectancy, profit factor y drawdown se calculan sobre el P&L neto combinado del par.

## Variantes vecinas (A9, fijadas aquí)

Umbral de entrada 1.5 / 2.5; ventana del z-score 120 / 480 velas; ventana de β 500 / 2 000 velas; sin filtro de cointegración.

## Criterio de éxito

Puerta A de la ADR 0002 sin cambios (salvo la definición de operación de arriba). Si falla, se descarta `pairs-v001`, no se prueban otros pares de divisas elegidos a posteriori y se pasa a la siguiente idea acordada (regímenes con mezclas gaussianas) o a la Fase 7.
