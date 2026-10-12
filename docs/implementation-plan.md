# Plan de implementación

> Regla: no se avanza de fase si fallan sus criterios de aceptación. Cada fase cierra con tests en verde, revisión de seguridad y `docs/progress.md` actualizado.

## Mapa de dependencias

```text
F0 Arquitectura
 └─► F1 Config/estructura
      ├─► F2 MT5 (mocks primero) ─┐
      ├─► F3 Crucix ──────────────┤
      │                           ▼
      │                     F4 Estrategia baseline
      │                           │
      └─► F5 Riesgo ◄─────────────┤   (F5 puede empezar en paralelo a F4 con tipos de F1/F2)
                                  ▼
                            F6 Backtesting ──► F7 Paper ──► F8 ML
                                                   │
                                  F9 API + dashboard (API desde F7; dashboard desde F9)
                                                   │
                                            F10 n8n ──► F11 VPS + demo ──► F12 Evaluación
```

Paralelizables:

| En paralelo | Condición |
|-------------|-----------|
| F2 ∥ F3 | ambos solo dependen de F1 |
| F4 ∥ F5 | contratos `Signal`, `SymbolSpec`, `AccountInfo` congelados en F1 |
| F6 métricas ∥ F6 engine | `ClosedTrade` definido |
| F9 dashboard ∥ F8 ML | la API de F7 ya expone datos |
| F10 ∥ F9 | endpoints de lectura listos |

## Fase 0 — Arquitectura (actual)

Tareas: README, architecture, risk-policy, model-policy, implementation-plan, progress, ADR 0001.
Aceptación: arquitectura y contratos documentados; módulos y dependencias definidos; riesgos listados; live bloqueado en el diseño; revisado y aprobado por Juan.

## Fase 1 — Configuración y estructura

| ID | Tarea |
|----|-------|
| 1.1 | `pyproject.toml` (Python 3.12, deps mínimas: pydantic, pydantic-settings, structlog, typer, pytest, ruff, mypy) |
| 1.2 | Árbol de paquetes vacío según `CLAUDE.md` §5 |
| 1.3 | `domain.py` con enums y contratos de `architecture.md` §5 (solo tipos) |
| 1.4 | `config.py` con `Settings` y validación fail-fast (§3 de architecture) |
| 1.5 | `.env.example` sin secretos |
| 1.6 | Logging estructurado con filtro de sanitización |
| 1.7 | CLI (`trading-system config check`, `trading-system version`) |
| 1.8 | Tests: config, sanitización, arquitectura de imports |
| 1.9 | CI (GitHub Actions): ruff, mypy, pytest, gitleaks |

Aceptación:
- `TRADING_MODE=live` y `LIVE_TRADING_ENABLED=true` hacen fallar el arranque (test en `tests/safety/`).
- Configuraciones ambiguas rechazadas (todas las reglas de architecture §3 con test).
- Ningún secreto aparece en logs (test).
- `pytest`, `ruff`, `mypy` en verde local y en CI.

## Fase 2 — Integración MT5 (sin órdenes)

| ID | Tarea |
|----|-------|
| 2.1 | Crear cuenta demo MT5 (manual, Juan) y anotar divisa de la cuenta, comisiones, spreads |
| 2.2 | `Mt5Client` implementando `MarketDataSource` |
| 2.3 | Conversión hora servidor → UTC |
| 2.4 | `SymbolSpec` y `AccountInfo` (login enmascarado) |
| 2.5 | `closed_bars` descarta la vela en formación |
| 2.6 | `FakeMt5` con fixtures (EURUSD, GBPUSD, USDJPY) |
| 2.7 | Descarga de histórico M15 a Parquet (`trading-system data download`) |
| 2.8 | Health check MT5 |

Aceptación: tests unitarios solo con `FakeMt5`; test de integración marcado `@pytest.mark.mt5` (opcional, excluido por defecto); `order_send` no aparece en el código (test grep); histórico descargado con hash.

## Fase 3 — Crucix

| ID | Tarea |
|----|-------|
| 3.1 | Levantar Crucix local y capturar respuestas reales como fixtures |
| 3.2 | Documentar el mapeo real → `MacroContext` (resuelve Q1) |
| 3.3 | `CrucixClient` con timeout, reintentos, caché |
| 3.4 | Fallback `unknown` + `data_stale` |
| 3.5 | `regime_classifier` basado en reglas simples (VIX, oro, curva) |
| 3.6 | Grabador de snapshots macro cada 15 min, encendido desde ya (es el único histórico macro que habrá) |

Aceptación: `current()` nunca lanza excepción (test con Crucix caído, timeout, JSON inválido, campos faltantes); política `MACRO_REQUIRED` probada en ambos valores.

## Fase 4 — Estrategia baseline

| ID | Tarea |
|----|-------|
| 4.1 | Indicadores (EMA 20/50/200, RSI, MACD, ATR, ADX) validados contra valores de referencia |
| 4.2 | Features técnicas |
| 4.3 | Reglas LONG/SHORT configurables |
| 4.4 | Todas las condiciones HOLD de `CLAUDE.md` §8 |
| 4.5 | Integración macro (penalización / bloqueo) |
| 4.6 | SL/TP propuestos por ATR |

Aceptación: cada condición HOLD tiene un test; la estrategia es determinista; sin look-ahead (test que trunca datos y compara).

## Fase 5 — Riesgo

| ID | Tarea |
|----|-------|
| 5.1 | Position sizing (ejemplos EURUSD y USDJPY de risk-policy como tests) |
| 5.2 | Validación de stops (stops_level, distancia mínima) |
| 5.3 | Límites y exposición |
| 5.4 | Circuit breaker persistente + kill switch |
| 5.5 | `RiskEngine` como único productor de `OrderIntent` |

Aceptación: tests de seguridad (`tests/safety/`): volumen nunca redondea hacia arriba; sin SL ⇒ rechazo; límites diarios; breaker sobrevive a reinicio; ningún otro módulo construye `OrderIntent`.

## Fase 6 — Backtesting

| ID | Tarea |
|----|-------|
| 6.1 | Engine por eventos (vela a vela), ejecución en `t+1` |
| 6.2 | Modelo de costes y fills (SL primero si ambos se tocan) |
| 6.3 | Métricas obligatorias de `CLAUDE.md` §12 |
| 6.4 | Reporte HTML/Markdown en `research/reports/` |
| 6.5 | Walk-forward |
| 6.6 | Sensibilidad a costes (×1, ×1.5, ×2) |
| 6.7 | Hold-out de 12 meses reservado y bloqueado por código hasta la evaluación final (ADR 0002) |
| 6.8 | Verificación automática de la Puerta A (A1–A10) en el reporte + registro de experimentos |

Aceptación: mismo config + mismos datos ⇒ mismo reporte (hash); test de no look-ahead; resultados siempre con costes. **No se declara rentabilidad.**

## Fase 7 — Paper trading

Tareas: `trading_loop` por vela cerrada, `PaperExecutor`, persistencia (SQLAlchemy + Alembic), reconciliación simulada, reportes diarios.
Aceptación: ≥ 2 semanas de paper sin errores no controlados; reinicio a mitad de sesión sin duplicados ni pérdida de estado; resultados de paper coherentes con backtest del mismo periodo.

## Fase 8 — Machine learning

Tareas: dataset de features técnicas + macro, labels TP/SL, splits con embargo, LightGBM, registry, walk-forward, comparación vs baseline.
Aceptación: según `docs/model-policy.md`. Un modelo que no supera a la baseline se rechaza; eso también es un resultado válido.

## Fase 9 — API y dashboard

Tareas: FastAPI con `X-API-Key`, endpoints de `CLAUDE.md` §14 + `/training/status`, dashboard React/Vite/Tailwind con estado, gráfico (Lightweight Charts), señales, operaciones, métricas, macro, kill switch.
Aceptación: tests de contrato de la API; ningún endpoint expone secretos ni crea órdenes; acciones peligrosas con confirmación; modo siempre visible.

## Fase 10 — n8n

Tareas: workflows retraining, alerts, daily-report, health-monitor, model-approval exportados a `workflows/n8n/`; Telegram.
Aceptación: n8n usa solo endpoints de la allowlist con key de scope reducido; alertas probadas apagando MT5/Crucix/BD.

## Fase 11 — VPS y demo

Tareas: instalación en VPS Windows, servicios con reinicio automático, backups y restauración probada, monitoreo, sincronización horaria, activación de `demo` con confirmación.
Aceptación: tras reinicio del VPS todo vuelve solo; restauración de backup probada; desconexión de MT5 ⇒ breaker + alerta; `DemoExecutor` se niega a operar en cuenta real (test con fake).

## Fase 12 — Evaluación

Checklist de `CLAUDE.md` §18 Fase 12 + Puertas B y C de la ADR 0002 + auditoría del Security Auditor Agent. El paso a dinero real **no** es parte de este proyecto; requeriría una ADR nueva y una decisión explícita fuera del MVP.

## Riesgos

### Técnicos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| `MetaTrader5` sin soporte para la versión de Python | no conecta | fijar Python 3.12 (ADR 0001) |
| Hora del servidor MT5 ≠ UTC / cambios de horario | velas desalineadas, look-ahead | conversión en la frontera + test |
| Usar la vela en formación | señales falsas | `closed_bars` descarta la última; test |
| Look-ahead en backtest/features | resultados inflados | ejecución en `t+1`, test de truncado, embargo en ML |
| Órdenes duplicadas tras timeout/reinicio | doble exposición | `intent_id` + UNIQUE en BD + consulta por comment antes de reintentar |
| Formato de Crucix desconocido o cambiante | contexto erróneo | fixtures reales, validación Pydantic, fallback `unknown` |
| `tick_value` variable (USDJPY) | lotaje mal calculado | leer en tiempo real / recalcular por vela; tests |
| Terminal MT5 se cuelga o desconecta | sin datos | health check + breaker + reinicio en VPS |
| Estado inconsistente tras reinicio | posiciones huérfanas | reconciliación al arranque; breaker abierto si no cuadra |
| Fuga de secretos (logs, git, API) | compromiso de cuenta | `.gitignore`, sanitización, gitleaks en CI, tests |

### Financieros / de método

| Riesgo | Mitigación |
|--------|------------|
| Sobreajuste (overfitting) de reglas o modelo | walk-forward, out-of-sample, pocas variantes, registro de todos los intentos |
| Ignorar costes reales | costes obligatorios + sensibilidad ×1.5/×2 |
| Muestra pequeña o un único periodo | mínimo de operaciones, varios años y regímenes, 3 símbolos |
| Spreads amplios en noticias / rollover | `max_spread`, filtro horario configurable |
| Gaps de fin de semana que saltan el SL | no mantener posiciones el viernes al cierre (configurable), pérdida real registrada |
| Diferencias backtest vs paper vs demo | comparar los tres en el mismo periodo antes de avanzar |
| Confundir buen backtest con ventaja real | regla de `CLAUDE.md`: no se declara rentabilidad sin out-of-sample |

## Primer sprint (propuesto)

Objetivo: Fase 1 completa, con live bloqueado y probado.

| Orden | Tarea | Resultado |
|-------|-------|-----------|
| 1 | Crear venv Python 3.12 | `.venv` |
| 2 | 1.1 + 1.2 | `pyproject.toml`, árbol de paquetes |
| 3 | 1.3 | `domain.py` con contratos |
| 4 | 1.4 + 1.5 | `config.py`, `.env.example` |
| 5 | 1.6 | logging con sanitización |
| 6 | 1.7 | CLI |
| 7 | 1.8 | tests unit + safety + arquitectura |
| 8 | 1.9 | CI en GitHub Actions |

Rama: `feat/phase-1-config`. Se mergea a `main` solo con tests en verde y con aprobación de Juan.

## Comandos de prueba (a partir de Fase 1)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

pytest                       # todo menos integración MT5
pytest tests/safety -v       # reglas de seguridad (live bloqueado, sin secretos, etc.)
pytest -m mt5                # integración con terminal MT5 demo (Fase 2+, manual)
ruff check . ; mypy src
trading-system config check  # valida la configuración actual
```
