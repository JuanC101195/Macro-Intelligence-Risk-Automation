# Progreso

## Estado actual

- **Fase:** 1 — Configuración y estructura (en la rama `feat/phase-1-config`, pendiente de merge)
- **Modo live:** bloqueado por configuración y por tipos (`OrderIntent.mode` no admite `live`); cubierto por tests
- **Conexión MT5:** ninguna
- **Modelos entrenados:** ninguno
- **Órdenes enviadas:** ninguna

## Registro

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
- [ ] CI en verde en GitHub (se verifica al abrir el PR)

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
