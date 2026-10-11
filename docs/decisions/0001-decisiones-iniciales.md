# ADR 0001 — Decisiones iniciales del MVP

- Fecha: 2026-10-11
- Estado: aceptada

## Contexto

Emprendimiento propio que arranca desde cero, siguiendo `CLAUDE.md`. El objetivo a largo plazo es operar con capital real **propio**. Eso solo se considerará después de la Fase 12, con evidencia fuera de muestra y una ADR nueva. Durante el MVP, live sigue bloqueado.
Antes de diseñar hubo que fijar algunas decisiones que `CLAUDE.md` deja abiertas.

## Decisiones

| # | Tema | Decisión | Motivo |
|---|------|----------|--------|
| 1 | Runtime Python | **Python 3.12** (instalado en el PC junto a 3.14) | El paquete `MetaTrader5` va por detrás de las versiones nuevas de Python; 3.12 cumple el requisito "3.12+" de forma segura. |
| 2 | Idioma | Docs en español; código, identificadores y commits en inglés | Lo habitual en el ecosistema y coherente con la estructura de `CLAUDE.md`. |
| 3 | Símbolos del MVP | `EURUSD`, `GBPUSD`, `USDJPY` en `M15` | Pocos majors FX. Incluir USDJPY obliga desde el inicio a manejar bien `point`/`digits`/`tick_value` (3 dígitos vs 5). |
| 4 | Crucix | **Opcional** en el MVP (`MACRO_REQUIRED=false`) | Si Crucix falla, el contexto pasa a `unknown`, la señal técnica sigue pero con penalización de confianza. Se cambia a obligatorio cuando el servicio sea estable (nueva ADR). |
| 5 | Base de datos | SQLite en desarrollo; PostgreSQL en Docker para integración y VPS | PostgreSQL no está instalado de forma nativa; Docker sí. |
| 6 | Cuenta MT5 | Aún no existe cuenta demo | Hasta la Fase 2 todo se prueba con mocks. La demo se crea al llegar a esa fase. |
| 7 | Repositorio | Local en `Desktop\intelligence-trading-platform`, remoto en GitHub creado manualmente | `gh` no está autenticado en este equipo. |
| 8 | Modo live | Bloqueado a nivel de código y configuración durante todo el MVP | Regla principal de `CLAUDE.md`. |
| 9 | Autenticación API | Header `X-API-Key` (variable `API_KEY`) | Simple, suficiente para el MVP, compatible con n8n. |
| 10 | Extensión de `OrderIntent` | Se añaden `intent_id` (clave de idempotencia) y `signal_bar_time` | Hacen falta para detectar órdenes duplicadas y reconciliar; ver `architecture.md` §5.6. |

| 11 | `OrderIntent.mode` admite `backtest` | El backtest reutiliza `RiskEngine`; con solo `paper`/`demo` habría que etiquetar mal las intenciones simuladas. |
| 12 | Riesgo por defecto 0.25 %; 0.5 % es el techo | Opción más conservadora del rango de `CLAUDE.md` §10. |
| 13 | Día de trading desde las 17:00 de Nueva York | Coincide con el rollover FX; no parte la sesión asiática. |
| 14 | Código propietario. Repo **público durante la fase de pruebas**; pasa a **privado antes de operar con capital real** | Decisión de Juan. Hacerlo privado después no retira lo ya publicado, por eso mientras sea público **no se suben** parámetros afinados, modelos entrenados, resultados de backtest ni datos de cuenta (van en archivos ignorados por git). `LICENSE` = "All rights reserved". |

## Consecuencias

- La configuración rechaza `TRADING_MODE=live` y `LIVE_TRADING_ENABLED=true`.
- Hay que documentar la conversión de `tick_value` para pares cuya divisa de beneficio no es la de la cuenta (USDJPY).
- El contrato de Crucix se verifica contra el servicio real en la Fase 3; hasta entonces se usan fixtures.
