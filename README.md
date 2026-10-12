# Intelligence Trading Platform

Plataforma experimental de inteligencia financiera y trading algorítmico: datos de MetaTrader 5, contexto macro de Crucix, estrategia técnica determinística, gestión de riesgo independiente, backtesting, paper trading y ejecución en cuenta **demo**.

> **Aviso.** Software propietario, uso interno. No es asesoría financiera. Las señales son experimentales. El modo `live` está bloqueado: el sistema no opera con dinero real.

## Estado

Fase 1 — configuración y estructura. Ver [`docs/progress.md`](docs/progress.md).

## Inicio rápido (Windows, PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env      # y completar localmente; .env nunca se sube

trading-system config check      # valida la configuración (falla si es insegura)
pytest                           # tests (excluye integración MT5)
pytest tests/safety -v           # reglas de seguridad
ruff check . ; mypy
```

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [`CLAUDE.md`](CLAUDE.md) | Requisitos y reglas del proyecto |
| [`docs/architecture.md`](docs/architecture.md) | Componentes, flujo y contratos entre módulos |
| [`docs/risk-policy.md`](docs/risk-policy.md) | Límites, lotaje, stops, circuit breaker |
| [`docs/model-policy.md`](docs/model-policy.md) | Validación y ciclo de vida de modelos ML |
| [`docs/implementation-plan.md`](docs/implementation-plan.md) | Fases, tareas, criterios de aceptación, primer sprint |
| [`docs/progress.md`](docs/progress.md) | Bitácora |
| [`docs/decisions/`](docs/decisions/) | ADRs (0002: criterios de éxito y de parada) |

## Alcance del MVP

- Símbolos: EURUSD, GBPUSD, USDJPY — timeframe M15.
- Modos: `backtest`, `paper` (por defecto), `demo` (requiere activación explícita). `live` bloqueado.
- Riesgo por operación: 0.25 %–0.5 % del equity; pérdida diaria máxima 2 %.

## Requisitos (a partir de Fase 1)

- Windows con terminal MetaTrader 5 (el paquete `MetaTrader5` solo funciona en Windows).
- Python 3.12.
- Node.js 20+ (Crucix y dashboard).
- Docker (PostgreSQL y n8n opcionales).
