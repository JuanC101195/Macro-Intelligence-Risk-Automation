# Progreso

## Estado actual (2026-10-12)

- **Fases completas:** 0 a 6 (arquitectura, configuración, MT5 solo lectura, Crucix + grabador, estrategia base, gestor de riesgo, backtest con Puerta A automática). Laboratorio de auditoría con vectorbt (ADR 0009).
- **Investigación:** 10 hipótesis probadas (ADR 0002 a 0008), **ninguna pasa la Puerta A**. Hold-out de 12 meses sin usar. El motor de backtest está auditado contra vectorbt sin bugs, y existe una prueba contra filtros aleatorios.
- **Modo live:** bloqueado por configuración y por tipos; cubierto por tests.
- **Conexión MT5:** solo lectura (cuenta demo, contraseña de inversor). **Órdenes enviadas:** ninguna. **Modelos activos:** ninguno.
- **Infraestructura:** VM de Azure grabando el contexto macro de Crucix 24/7 desde 2026-10.

### Próximos pasos acordados

1. **ADR 0010 — criterio A11:** toda hipótesis debe superar el percentil 95 de su versión aleatoria (entradas o filtros al azar con la misma frecuencia), pre-registrado junto con la hipótesis.
2. **Fase 7 — paper trading y base de datos:** loop de velas cerradas, paper executor, persistencia y reconciliación simulada, para medir spreads, slippage y comportamiento reales mientras Crucix acumula historia propia.
3. Investigación nueva solo con una fuente de ventaja con fundamento propio (historia macro de Crucix, COT de la CFTC, eventos), pre-registrada y con A11.

## Registro

### 2026-10-12 — vectorbt como laboratorio (ADR 0009) — rama `feat/vectorbt-lab`

- vectorbt 1.1.2 (Apache 2.0 + Commons Clause) como extra opcional `research` en un `.venv-research` aparte; un test de arquitectura impide importarlo (ni numba ni sklearn) desde el paquete. CI no cambia.
- **Prueba 1 — auditoría del motor: pasa.** GMM propio = scikit-learn hasta 1e-13. Motor propio contra `Portfolio.from_signals` en la ruptura H4 (11 instrumentos, costes en cero): todas las operaciones explicadas, la gran mayoría idénticas y el resto por cuatro convenciones documentadas en las que el motor propio es más prudente. **Ningún bug del motor**; los errores encontrados eran del script de auditoría.
- **Prueba 2 — filtro de regímenes contra 200 filtros aleatorios: no pasa.** El GMM no supera el percentil 95 de los filtros al azar; casi toda la mejora frente al control también la logra un filtro aleatorio. Se abandona la línea de regímenes (pre-registrado).
- Lección de método: toda mejora relativa (filtro, variante) se compara contra una versión aleatoria equivalente antes de interpretarla.

### 2026-10-12 — H-REGIME-1 (ADR 0008): ruptura H4 con filtro de regímenes GMM — rama `feat/regimes-gmm`

- Pre-registro (ADR 0008) commiteado antes del código, con la profundidad H4 encontrada al descargar (índices desde 2012-08 → se opera desde 2014-08); código commiteado antes de las corridas.
- Implementado: `strategy/regimes.py` (características vol/er, mezcla gaussiana 2-D por EM en Python puro, reajuste semestral solo con el pasado, sin ventana incompleta), ruptura con timeframe configurable y filtro de régimen opcional, cálculo paralelo por instrumento, comando `backtest regime [--control]`. 14 tests nuevos (incluye "cambiar el futuro no cambia las etiquetas del pasado"); 392 en verde.
- **Control `breakout-h4-v001`: no pasa.** En H4 la muestra ya alcanza la A2, pero es negativa, con drawdown muy por encima del límite y vecinas mayoritariamente negativas.
- **Principal `regime-h4-v001`: no pasa**, aunque es la primera hipótesis con expectancy positiva con costes ×1 y ×1.5. Falla profit factor mínimo (A4), ventanas positivas (A6), drawdown (A7, por poco), dependencia del mejor año (A8) y estabilidad (A9: la mitad de las vecinas negativas). Frente al control, el filtro mejora claramente el profit factor y reduce el drawdown a la mitad. Hold-out no usado.
- Lectura: el filtro de régimen aporta algo frente al control, pero el resultado depende de los parámetros del GMM (pico, no meseta) y de un año concreto. Pendiente antes de creer siquiera la mejora relativa: comparar contra un filtro **aleatorio** que bloquee la misma proporción de señales.
- Tentación registrada y descartada: elegir K = 4 o 3 años de entrenamiento (las vecinas positivas) sería seleccionar a posteriori.
- Balance: **10 hipótesis probadas (contando control y principal), ninguna pasa la Puerta A**.

### 2026-10-12 — H-PAIRS-1 (ADR 0007): arbitraje estadístico AUDUSD–NZDUSD — rama `feat/pairs-aud-nzd`

- Pre-registro (ADR 0007) y adenda de implementación (ADF con 1 rezago y valor crítico de MacKinnon, escalado proporcional de las patas, racha de pérdidas por par) commiteados **antes** del código; código commiteado antes de la corrida.
- Datos: AUDUSD y NZDUSD en H1 desde 2010-09 (descargados con hash, locales).
- Implementado: `strategy/pairs.py` (OLS, ADF y z-score en Python puro, solo con datos pasados), `backtest/pairs_engine.py` (motor de dos patas: decisión solo en horas comunes, todo o nada en la aprobación y en el fill, la pata huérfana se cierra en la apertura siguiente sin look-ahead, una operación = un par), `risk_fraction` opcional en el gestor de riesgo (solo puede **bajar** el riesgo por operación), comando `backtest pairs`. 21 tests nuevos (precios calculados a mano); 378 en verde.
- Resultado: **no pasa la Puerta A**. Negativa con costes ×1, muy pocas operaciones (falla A2: el filtro de cointegración bloquea la mayoría de las señales) y **las 7 vecinas también negativas**. Hold-out no usado.
- Revisión del resultado (regla 3): (1) la mayoría de los pares sale por el **stop de protección de una pata** (4 × ATR H1): las dos monedas se mueven juntas frente al USD y la pata perdedora toca su stop aunque el diferencial siga sano; es la regla pre-registrada, no un bug, pero convierte el par en dos apuestas direccionales. (2) Hueco en la regla de entrada: sin tope superior, con |z| ≥ 4 el sistema entraba y salía en la vela siguiente por el stop del diferencial; afecta a una fracción pequeña de operaciones y quitarlas no cambia la conclusión.
- Tentación registrada y descartada: "con stops de pata más amplios y entrada acotada a 2 ≤ |z| < 4 funcionaría". Sería ajustar la regla a los datos ya vistos; si se prueba, es una hipótesis nueva con su ADR y sin reutilizar este periodo como evidencia.
- Balance: **8 hipótesis probadas, ninguna pasa la Puerta A**. Según la ADR 0007 no se prueban otros pares de divisas elegidos a posteriori.

### 2026-10-12 — Capital real (ADR 0005) y H-BREAKOUT-1 (ADR 0006) — rama `feat/breakout`

- **ADR 0005:** el capital real futuro es 100 000–700 000 COP (≈ 25–175 USD). Solo es operable en cuenta cent; los backtests nuevos simulan el equivalente (17 500 con lotes estándar). Metas realistas: 10–25 % anual con drawdown ≤ 10 %; "100 USD/semana" con ese capital no es alcanzable y no se perseguirá.
- **ADR 0006 (pre-registrada antes del código):** ruptura de canal Donchian 55/20, stop 2 × ATR, D1, metales (XAUUSD, XAGUSD), índices (US500, US30) y 7 pares FX, máximo 3 posiciones. Adendas antes de correr: USTEC excluido (historia solo desde 2022-07); take-profit no vinculante de los SHORT con piso del 10 % del precio (podía ser negativo).
- Implementado: registro de instrumentos con specs de MT5 (`backtest/instruments.py`), P&L/margen por instrumento, slippage por símbolo, financiación por clase de activo (`backtest/financing.py`), `strategy/breakout.py`, comando `backtest breakout`.
- Resultado (2012-08 → 2025-10): **no pasa la Puerta A**; levemente negativo, vecinas negativas. Con el capital equivalente a la cuenta cent, oro y plata casi no se pudieron operar (lote mínimo) y los límites de 3 posiciones / exposición USD 1× impiden la diversificación que el trend following necesita. Hold-out no usado.
- Balance de investigación: **7 hipótesis probadas** (baseline M15/H1/H4, filtro macro block/confirm, carry, ruptura multi-activo), **ninguna pasa la Puerta A**.

### 2026-10-12 — H-CARRY-1 (ADR 0004): carry de divisas — rama `feat/carry`

- Pre-registro (ADR 0004) commiteado antes del código; código commiteado antes de cada corrida.
- Implementado: tasas FRED punto-en-el-tiempo (`macro/rates.py`, disponibles en M+2), `strategy/carry.py`, y en el motor: salidas por señal, swap diario, procesamiento en dos pasadas de velas simultáneas, conversión de P&L para todos los USDXXX, exposición por divisa configurable. Comandos `data rates` y `backtest carry`. 7 pares × 16 años D1.
- **Corrida 1 inválida** (documentada en la adenda de la ADR 0004): el mínimo de 0.01 lotes con 10 000 USD y un falso positivo de `tick_value_mismatch` del gestor de riesgo descartaban ~80 % de las señales. Corregido: dimensionamiento con la estimación de pérdida más conservadora y verificación de `tick_value` con tolerancia proporcional al stop; capital de simulación 100 000 USD.
- **Bug encontrado al revisar la corrida 2**: las posiciones abiertas al final del periodo de investigación se fechaban al final del archivo y **acumulaban swap más allá del corte del hold-out**, inflando el resultado. Corregido con test; la corrida 3 es la válida.
- Resultado válido: **no pasa la Puerta A**. En 15 años queda prácticamente en el punto de equilibrio, con muy pocas operaciones (falla A2) y vecinas inestables (unas positivas, otras negativas). Los años 2010-2015 (tasas cerca de cero) son negativos, como anticipaba el prior. Hold-out no usado.
- Tentación registrada y descartada: "el carry funciona cuando las tasas son altas" se ve sugerente en algunos años, pero formularlo ahora sería ajustar la hipótesis a los datos ya vistos.
- Hallazgo práctico: con 10 000 USD no es viable un carry diario con 0.25 % de riesgo por operación (mínimo de 0.01 lotes).

### 2026-10-12 — H-MACRO-1 (ADR 0003): filtro de régimen con historia de FRED — rama `feat/fred-macro-filter`

- Pre-registro (ADR 0003) y adenda de datos (spread HY solo desde 2023-10) commiteados **antes** de ejecutar; código commiteado antes de las corridas.
- `macro/fred_history.py`: contexto macro punto-en-el-tiempo desde FRED (VIX, HY, curva) con disponibilidad D+1 22:00 UTC; `trading-system data fred`; `backtest run --macro-filter block|confirm`.
- Resultado en H1 (15 años): **ninguna variante pasa la Puerta A**. `block` reduce las pérdidas frente a la estrategia sin filtro pero sigue negativa; `confirm` elimina ~90 % de las operaciones y lo que queda está en torno a cero (muestra insuficiente para A2). Las vecinas también fallan. Hold-out no usado.
- Conclusión según la ADR 0003: se descarta el filtro macro sobre la familia de señales de tendencia. Presupuesto usado: 14 de 20. La historia de FRED queda disponible para hipótesis con fundamento económico propio.

### 2026-10-12 — Hipótesis: misma lógica en timeframes mayores — rama `feat/higher-timeframes`

- Backtest con `--tf` (M15/H1/H4); cada timeframe es una hipótesis con versión propia (`baseline-v001-h1`, `-h4`) y su propio presupuesto de variantes. Las variantes vecinas (A9) heredan el timeframe (test añadido: antes se habrían evaluado en M15 sin aviso).
- Datos: MetaQuotes-Demo tiene ~16 años de H1/H4 (desde 2010-09) en los tres pares; descargados con hash (locales).
- Resultado: **ninguna de las dos pasa la Puerta A**. H1 se comporta como M15 (sin ventaja). H4 queda cerca del punto de equilibrio con pocas operaciones: no hay ventaja demostrable. Detalle en los reportes locales; hold-out no usado.
- Conclusión: la familia "tendencia EMA + pullback RSI + MACD + ADX" no muestra ventaja en EURUSD/GBPUSD/USDJPY en ningún timeframe probado. Según la ADR 0002 se deja de ajustar esta familia (se gastaron 7 variantes en cada una de las 3 hipótesis) y se pivota.
- Tentación registrada y descartada: USDJPY en H4 aislado se ve positivo, pero elegir un par después de ver los resultados es sesgo de selección; además son ~70 operaciones (estadísticamente insuficiente). Si se quisiera probar, tendría que ser una hipótesis nueva, escrita antes, y evaluada en datos que no se hayan mirado.

### 2026-10-12 — Fase 6 (backtesting) — rama `feat/phase-6-backtest`

Hecho:
- `backtest/engine.py`: motor por eventos multi-símbolo en orden cronológico (los límites de riesgo son de cartera). Mismo camino que en vivo: `decide()` de la estrategia → `DefaultRiskEngine` → `OrderIntent`. Ejecución en la apertura de la vela siguiente; órdenes pendientes cuentan para el límite de posiciones; no se ejecuta a través de huecos de datos.
- `backtest/fills.py`: SL antes que TP si la vela toca ambos; gap a través del stop sale en la apertura; SHORT sale al ask (bid + spread); stops con slippage, TP sin mejora.
- `backtest/costs.py`: spread fijo minorista por símbolo (no el de MetaQuotes-Demo), slippage, comisión; multiplicador para ×1.5 / ×2.
- `backtest/metrics.py`: todas las métricas de `CLAUDE.md` §12. `walk_forward.py`: ventanas de 6 meses. `gates.py`: **Puerta A (A1–A10) automática** con los umbrales de la ADR 0002; **hold-out de 12 meses bloqueado por código** y de un solo uso.
- `trading-system backtest run`: corre costos ×1/×1.5/×2, walk-forward y 6 variantes vecinas (A9, fijadas antes de ver resultados); escribe reporte Markdown/JSON en `research/reports/` y registra el experimento en `research/experiments.jsonl` (ambos locales, no se suben: ADR 0001 #14).
- Tests de mecánica con precios calculados a mano (entrada, costos, SL primero, gaps, ask de los SHORT, cancelación por huecos, límite de cartera, reproducibilidad); 317 tests en verde.

Primera corrida de investigación (`baseline-v001`, 3 pares, ~3 años sin el hold-out): **no pasa la Puerta A**. El resultado es coherente internamente (no hay indicios de bug) y robusto a las variantes vecinas: la hipótesis no tiene ventaja. Detalle en el reporte local. El hold-out **no** se usó.

Criterios de aceptación de la Fase 6:
- [x] Mismo config + mismos datos ⇒ mismo resultado (digest)
- [x] Sin look-ahead (ejecución en t+1; indicadores causales)
- [x] Resultados siempre con costos
- [x] No se declara rentabilidad

### 2026-10-12 — Fase 5 (riesgo) — rama `feat/phase-5-risk`

Hecho:
- `risk/position_sizing.py`: fórmula de `risk-policy.md` §2; siempre redondea hacia abajo; rechaza bajo el mínimo del broker (nunca redondea hacia arriba); tope en el máximo. Ejemplos EURUSD y USDJPY de la política como tests (0.12 lotes, 24 USD) + 2 000 casos aleatorios: el riesgo real nunca supera el permitido.
- `risk/circuit_breaker.py`: estado en JSON con escritura atómica; sobrevive reinicios; archivo corrupto ⇒ arranca **abierto**; conserva la primera causa; reset solo manual con operador y motivo; kill switch; historial auditable.
- `risk/exposure.py`: día de trading desde las 17:00 de Nueva York con DST; patas por divisa; riesgo hasta el SL de una posición.
- `risk/engine.py` (`DefaultRiskEngine`): **único** constructor de `OrderIntent` (test AST en `tests/safety`). Controles: breaker, cuenta demo, símbolo operable, short permitido, spread, posiciones/operaciones/pérdidas consecutivas, pérdida diaria actual; entrada desde ask/bid real, precio no pasado del SL/TP, deriva de entrada ≤ 50 %, distancia mínima de stops; tamaño; **pérdida diaria en el peor caso** (realizada + riesgo hasta SL de lo abierto + lo nuevo); exposición por divisa en la misma dirección; margen ≤ 50 % del libre; verificación cruzada con `order_calc_profit` (detecta `tick_value` mal interpretado).
- Disparan el breaker: cuenta no demo, pérdida diaria alcanzada, máximo de pérdidas consecutivas, posición abierta sin SL.
- 280 tests en verde; ruff y mypy limpios.

Criterios de aceptación de la Fase 5:
- [x] El volumen nunca redondea hacia arriba
- [x] Sin SL ⇒ rechazo (y posición abierta sin SL dispara el breaker)
- [x] Límites diarios (actual y peor caso)
- [x] El breaker sobrevive a un reinicio y falla cerrado ante estado inconsistente
- [x] Ningún otro módulo construye `OrderIntent`

### 2026-10-12 — Quality gate de SonarQube en `main`

- Estado del repo: PRs #1–#6 mergeados, CI en verde; el quality gate de SonarQube fallaba por confiabilidad C (un test comparaba una expresión consigo misma) y 11 hallazgos menores.
- Corregido en `fix/sonar-quality-gate`: `uv.lock` como fuente única de dependencias (CI con `uv sync --frozen`, sin construir el proyecto; imagen Docker desde `uv export` con hashes); acciones de GitHub fijadas por SHA completo; `classify()` y `adx()` divididos en funciones pequeñas (mismos resultados, tests de referencia en verde); tests de excepciones más precisos.

### 2026-10-12 — Fase 4 (estrategia base `baseline-v001`) — rama `feat/phase-4-strategy`

Hecho:
- `strategy/indicators.py`: SMA, EMA, RSI, MACD, ATR, ADX con convención Wilder/TA-Lib; `None` durante el calentamiento. **RSI coincide exactamente con el ejemplo publicado de StockCharts** (70.53 … 37.77). EMA y ATR verificados a mano; ADX con propiedades (tendencia vs rango, primer valor en 2×periodo−1). Test de no look-ahead para todos.
- `strategy/baseline.py`: reglas LONG/SHORT de `CLAUDE.md` §8 con umbrales fijos (EMA50/200, pullback RSI 40/60 en 5 velas, MACD, ADX ≥ 20); SL = 1.5×ATR desde ask/bid, TP = 2×SL; la estrategia no decide volumen. Hipótesis macro v001: risk_off bloquea LONG, risk_on bloquea SHORT; macro desconocido solo penaliza confianza (×0.8) salvo `MACRO_REQUIRED`.
- `decide()` es una función pura; reporta **todos** los motivos de HOLD a la vez (datos insuficientes, vela no cerrada, datos obsoletos, indicadores sin calentar, spread, posición abierta, riesgo bloqueado, símbolo no operable, macro no disponible/contradictorio, short no permitido, sin setup con detalle de qué condición falló).
- `strategy/features.py`: las 19 features técnicas de `CLAUDE.md` §9 por vela, sin look-ahead.
- 223 tests en verde; ruff y mypy limpios. `TIMEFRAME_MINUTES` movido a `domain.py`.

Censo de señales en datos reales (no es backtest: sin P&L ni costos; 1 de cada 4 velas del último año, spread fijo de 10 puntos, macro `unknown`): ~0.25 % de las velas dan señal, LONG y SHORT balanceados en los tres pares (≈110–160 señales/año/par). Frecuencia compatible con el mínimo de 300 operaciones OOS de la ADR 0002.

Criterios de aceptación de la Fase 4:
- [x] Cada condición de HOLD tiene un test
- [x] Estrategia determinista (mismo input → misma señal)
- [x] Sin look-ahead (test de prefijos en indicadores y features)

### 2026-10-12 — Grabación macro 24/7 en Azure for Students

- VM `vm-itp-macro` (Spain Central, B2ats v2, sin puertos de entrada) con Docker Compose: Crucix (commit revisado, sin puertos publicados) + grabador. Detalles y comandos en `docs/operations.md`.
- Verificado: Crucix `healthy`, 0 reinicios, 28/29 fuentes; grabador escribiendo snapshots reales (`risk_on`, VIX 14.84).
- Presupuesto `itp-monthly` de 10 USD/mes con avisos por correo. La suscripción no tiene tarjeta: no puede generar cobros reales.
- Fallos encontrados y corregidos durante el despliegue: B1s sin capacidad, scripts multilínea en `az`, uid del contenedor, `safe.directory` de git, y Crucix sin heap suficiente (bucle de reinicios).
- El PC sigue grabando en paralelo unos días como respaldo.

### 2026-10-11 — Crucix real en local

- Crucix instalado en `Desktop\Crucix`, fijado al commit revisado `3db7068` (`npm ci --omit=optional`; solo `express` y sus dependencias). Licencia AGPL: se usa sin modificar y por HTTP.
- Escucha en todas las interfaces (`app.listen(port)` sin host): se bloquea con el firewall de Windows; nuestro cliente usa `127.0.0.1`.
- Primer barrido: 27/29 fuentes OK en ~30 s. `trading-system macro check` contra datos reales: `risk_on`, conf 0.62, VIX 14.84, curva +0.44, HY 3.15, salud 0.93.
- Tarea 3.1 hecha: respuesta real guardada como `tests/fixtures/crucix_real_20261012.json` (subconjunto, sin historiales) con test.
- `conflict_events` = 0 porque ACLED requiere cuenta propia; no es señal útil hasta configurarla.

### 2026-10-11 — Grabación macro persistente en el PC (provisional)

- Tareas del Programador de Windows `ITP-Crucix` y `ITP-MacroRecorder` (al iniciar sesión, sin admin, sin límite de tiempo, funcionan con batería). Scripts en `infra/windows/`; quitar con `register-tasks.ps1 -Unregister`. Logs en `%LOCALAPPDATA%\itp\logs`.
- Primer snapshot real grabado 2026-10-12 01:38 UTC (`risk_on`, VIX 14.84).
- Problemas encontrados y corregidos:
  - PowerShell 5.1 + redirección de stderr + `ErrorActionPreference=Stop` mataba a Crucix y al grabador → la redirección la hace `cmd.exe`.
  - El grabador arrancaba antes de que `/api/data` respondiera (503 al inicio de Crucix) → espera a `/api/data` 200.
  - Detener la tarea no mata a los procesos hijos → quedaron grabadores huérfanos que habrían duplicado snapshots. **Candado de instancia única** en el grabador (bloqueo del SO, se libera si el proceso muere); un segundo grabador sale con código 3.
- Los 3 primeros snapshots de hoy son `unknown` (arranques fallidos); se mantienen porque son la verdad de ese momento.
- Solo graba con el PC encendido. Siguiente: VM Linux en Azure for Students con Docker Compose (Crucix + grabador).

### 2026-10-11 — Conexión real a MT5 y descarga de histórico

- Cuenta **demo** MetaQuotes-Demo, USD, 10 000, 1:100, login `****9960`. Conectada con la **contraseña de inversor**: `trade_allowed=False`, MT5 rechazaría cualquier orden. La contraseña principal no está en `.env` hasta la Fase 11.
- `trading-system mt5 check` en verde. Diferencia horaria del servidor: **UTC+3 (180 min)**, observada en vivo y configurada.
- **Q3 resuelta:** el servidor tiene ~4.1 años de M15 (desde septiembre de 2022) en los tres pares, aun con el límite de barras en "Ilimitado". Con 12 meses de hold-out quedan ~3.1 años para investigación: cumple A1 (≥ 3 años) con poco margen.
- Descargados `EURUSD`, `GBPUSD`, `USDJPY` M15 (~100 k velas cada uno) en `research/datasets/` con manifiesto y sha256 (local, no se sube).
- Calidad de datos:
  - Huecos: feriados de fin de año (esperado) y **un corte de 12 h el 2024-07-02 en los tres pares**. El backtest debe tolerar huecos sin operar a través de ellos.
  - **Spreads de MetaQuotes-Demo irreales**: EURUSD con spread 0 en el 51 % de las velas (mediana 0); GBPUSD mediana 4 puntos, USDJPY 3. **El backtest no usará el spread histórico de esta fuente**: usará un spread fijo realista + comisión (`CostModel.spread_mode="fixed"`), y la sensibilidad ×1.5/×2 de la ADR 0002.
- Bug corregido: `N8N_BASE_URL` vacío impedía arrancar con una copia de `.env.example`. Test añadido.

### 2026-10-11 — Fase 3 (Crucix) — rama `feat/phase-3-crucix`

Hecho:
- Contrato de Crucix verificado leyendo su código (commit `3db7068`, 2026-05-19): `/api/data` devuelve 503 hasta el primer barrido; FRED trae números o `null`; VIX en vivo desde Yahoo Finance; no hay histórico consultable. Mapeo documentado en `macro/crucix_client.py` (resuelve Q1 a nivel de código).
- `macro/crucix_client.py`: `normalize()` pura y tolerante (tipos raros, NaN, timestamps sin zona o futuros → `None`/`unknown`). `CrucixClient` con timeout, reintentos solo ante 5xx/errores de red, caché de 5 min; `current()` nunca lanza excepción.
- `macro/regime_classifier.py`: reglas `regime-rules-v001` con umbrales redondos fijados antes de cualquier backtest (VIX 16/25, spread HY 3.5/5.0, oro +1.5 %, curva invertida solo refuerza).
- `macro/recorder.py` + `trading-system macro record`: graba un snapshot por intervalo en JSONL mensual (contexto + subconjunto crudo para re-derivar features). Local, no se sube.
- `trading-system macro check`. URLs de Crucix/n8n validadas (solo http(s), sin credenciales ni query).
- 173 tests en verde; ruff y mypy limpios.

Notas:
- Con Crucix apagado, en Windows cada conexión rechazada tarda ~2 s: `macro check` tarda ~13 s antes de responder `unknown`. En el ciclo de trading (Fase 7) la consulta macro irá en segundo plano.
- Los fixtures son sintéticos con la forma real. Pendiente 3.1: levantar Crucix (`npm install`, claves gratuitas como FRED) y capturar respuestas reales.

### 2026-10-11 — Fase 2 (MT5, solo lectura) — rama `feat/phase-2-mt5`

Hecho:
- `broker/mt5_client.py`: `Mt5Client` de solo lectura (cuenta, símbolos, ticks, velas cerradas, rango histórico, posiciones, `calc_margin`/`calc_profit`). El módulo `MetaTrader5` se inyecta para poder testear con un fake.
- La vela en formación nunca se devuelve. Login siempre enmascarado. Errores sin credenciales.
- Hora del servidor → UTC con diferencia **configurada** y verificación cruzada contra ticks frescos (detecta cambios de DST). **Bug encontrado por test y corregido:** deducir la diferencia solo con ticks aceptaba valores falsos con ticks viejos.
- `broker/history.py`: descarga a Parquet + manifiesto con sha256 (reproducibilidad).
- CLI: `trading-system mt5 check` (sale con código 2 si la cuenta no es demo; sugiere la diferencia horaria) y `trading-system data download`.
- `tests/fixtures/fake_mt5.py`: MT5 simulado con hora de servidor UTC+3 y vela en formación. Test de integración real marcado `mt5` (excluido por defecto).
- 130 tests en verde; ruff y mypy limpios. Contra el terminal real: falla limpio (`IPC timeout`) porque aún no hay cuenta demo.

Pendiente de Fase 2:
- Crear la cuenta demo (Juan), configurar `.env`, correr `trading-system mt5 check` y `pytest -m mt5`.
- Descargar el histórico M15 de los 3 símbolos y verificar profundidad (Q3: ¿≥ 3 años + 12 meses de hold-out?).
- Verificar si el broker conserva el `comment` (Q6) — se hace en la Fase 11 con órdenes demo.

### 2026-10-11 — Fase 1 (sprint 1)

Hecho:
- `pyproject.toml` (Python 3.12, hatchling), `.env.example`, `.gitattributes` (LF).
- `config.py`: `Settings` con validación fail-fast. Rechaza `live`, demo sin opt-in, opt-in fuera de demo, límites de riesgo por encima de los techos, `MACRO_REQUIRED` sin Crucix, producción sin `API_KEY`. Los errores nunca muestran valores.
- `domain.py` y contratos como tipos: `broker/contracts.py`, `macro/macro_context.py`, `strategy/signals.py`, `models/schemas.py`, `risk/contracts.py`, `execution/order_intent.py`. Validan horquilla SL/entrada/TP, fechas con zona horaria, `intent_id` determinista.
- Logging estructurado (structlog) con `SecretScrubber`: redacta claves sensibles y cualquier valor secreto conocido, también dentro de excepciones.
- CLI: `trading-system version`, `trading-system config check`.
- Tests: 85 en verde (unit + safety: live bloqueado, sin fugas de secretos, reglas de imports). `ruff` y `mypy --strict` limpios.
- CI en GitHub Actions: ruff, mypy, pytest y gitleaks.

Desviaciones del plan:
- `OrderGateway` (envío de órdenes) no se definió: se añade en la Fase 11 junto con el executor demo, para que no exista ningún camino de envío antes.
- Los contratos de backtest, storage y API se definen en sus fases (6, 7, 9).

Criterios de aceptación de la Fase 1:
- [x] `TRADING_MODE=live` y `LIVE_TRADING_ENABLED=true` hacen fallar el arranque (env, `.env` y argumentos)
- [x] Configuraciones ambiguas rechazadas, cada regla con test
- [x] Ningún secreto en logs, CLI ni mensajes de error
- [x] `pytest`, `ruff`, `mypy` en verde local
- [x] CI en verde en GitHub (PR #1 y `main`)

### 2026-10-11 — ADR 0002

- Criterios de éxito (Puertas A, B, C) y de parada/pivote fijados antes de cualquier backtest.
- Hold-out de 12 meses y presupuesto de 20 variantes por hipótesis.

### 2026-10-11 — Fase 0

Hecho:
- Repo creado en `Desktop\intelligence-trading-platform` (git local, sin remoto).
- `CLAUDE.md` copiado desde `CLAUDE_Version4.md`.
- Docs: `README.md`, `architecture.md` (contratos), `risk-policy.md`, `model-policy.md`, `implementation-plan.md`, ADR 0001.
- `.gitignore` con exclusión de secretos, datos y artefactos.

Autorrevisión de la Fase 0 (mismo día) y correcciones:
- Faltaba un límite de exposición por divisa (EURUSD y GBPUSD correlacionados).
- La pérdida diaria no contaba el riesgo hasta el SL de las posiciones abiertas.
- Las velas de MT5 son bid: hay que disparar SL/TP de los SHORT con `bid + spread`.
- La entrada real sale del tick (ask/bid), no del `close`; el volumen se recalcula.
- Crucix no tiene histórico: se graban snapshots desde la Fase 3 y no se inventa contexto en el backtest.
- `OrderIntent.mode` no contemplaba `backtest`.
- La deduplicación dependía solo del comment de MT5, que algunos brokers reescriben.
- El día de trading pasa de medianoche UTC al rollover de las 17:00 de Nueva York.

Decisiones: ver `docs/decisions/0001-decisiones-iniciales.md`.

Pendiente:
- Revisión y aprobación de la Fase 0 por Juan.
- Crear el repositorio en GitHub y enlazarlo como remoto.
- Primer commit (cuando se apruebe).

## Criterios de aceptación de la Fase 0

- [x] Arquitectura documentada
- [x] Módulos definidos
- [x] Contratos definidos
- [x] Riesgos documentados
- [x] Live bloqueado en el diseño
- [ ] Aprobada por Juan
