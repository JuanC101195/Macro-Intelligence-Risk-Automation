# Progreso

## Estado actual

- **Fase:** 1 completa (PR #1 mergeado, CI en verde). Siguiente: Fases 2 y 3.
- **Criterios de éxito y parada:** fijados en ADR 0002 antes de ver resultados
- **Modo live:** bloqueado por configuración y por tipos (`OrderIntent.mode` no admite `live`); cubierto por tests
- **Conexión MT5:** ninguna
- **Modelos entrenados:** ninguno
- **Órdenes enviadas:** ninguna

## Registro

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
