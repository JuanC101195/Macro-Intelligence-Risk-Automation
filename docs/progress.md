# Progreso

## Estado actual

- **Fase:** 0 — Arquitectura (pendiente de aprobación)
- **Modo live:** bloqueado (solo diseño; aún no hay código)
- **Conexión MT5:** ninguna
- **Modelos entrenados:** ninguno
- **Órdenes enviadas:** ninguna

## Registro

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
