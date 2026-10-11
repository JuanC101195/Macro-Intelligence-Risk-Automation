# Intelligence Trading Platform

## 1. Rol de Claude

Actúa como arquitecto principal, desarrollador full-stack, ingeniero de datos,
ingeniero de machine learning, especialista en MetaTrader 5, DevOps y auditor
de seguridad financiera.

Debes construir el proyecto de forma incremental, modular, documentada,
reproducible y segura.

No debes asumir que una estrategia es rentable porque tenga un buen resultado
histórico. El sistema debe demostrar primero que es técnicamente correcto y
después evaluar si existe una ventaja estadística fuera de muestra.

## Regla principal

Durante todo el MVP:

- no se permite operar con dinero real;
- el modo `live` debe permanecer bloqueado;
- las operaciones iniciales serán backtest, paper trading y cuenta demo;
- ninguna API key real debe guardarse en el repositorio;
- ningún modelo de IA puede decidir directamente cuánto dinero arriesgar;
- toda orden debe pasar por el gestor de riesgo;
- todo resultado financiero debe incluir costes realistas.

---

# 2. Objetivo del producto

Construir una plataforma full-stack de inteligencia financiera y trading
algorítmico que combine:

1. Datos de MetaTrader 5.
2. Indicadores técnicos.
3. Contexto macroeconómico y OSINT desde Crucix.
4. Machine learning opcional.
5. Gestión de riesgo.
6. Backtesting.
7. Paper trading.
8. Ejecución en cuenta demo.
9. Dashboard web.
10. Alertas y automatización mediante n8n.
11. Despliegue 24/7 en un VPS.

La plataforma debe producir señales como:

```json
{
  "symbol": "EURUSD",
  "timeframe": "M15",
  "signal": "LONG",
  "confidence": 0.72,
  "technical_score": 78,
  "macro_regime": "risk_on",
  "entry": 1.0825,
  "stop_loss": 1.0805,
  "take_profit": 1.0865,
  "risk_percent": 0.5,
  "volume_lots": 0.1,
  "mode": "paper",
  "model_version": "baseline-v001"
}
```

El resultado no es una recomendación financiera garantizada. Es una señal
experimental con información, razones, riesgo y condiciones de invalidación.

---

# 3. Visión de arquitectura

```text
                         ┌─────────────────────┐
                         │       Crucix        │
                         │ Macro / OSINT / News│
                         │ Risk-on / Risk-off  │
                         └──────────┬──────────┘
                                    │ HTTP / JSON
                                    ▼
┌──────────────┐          ┌──────────────────────┐
│     MT5      │─────────▶│  Python Trading Core │
│ Broker data  │          │                      │
│ Velas        │          │ Technical strategy  │
│ Ticks        │          │ ML predictions      │
│ Spread       │          │ Macro context       │
│ Account      │          │ Risk engine         │
└──────────────┘          │ Paper/demo executor │
                          └──────────┬───────────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
            PostgreSQL          FastAPI             n8n
             histórico          API REST          workflows
                  │                  │                  │
                  └──────────────────┼──────────────────┘
                                     ▼
                              React Dashboard
```

## Responsabilidades

### Python

Python será el núcleo del sistema:

- conexión con MT5;
- obtención y validación de datos;
- indicadores;
- estrategia;
- features;
- modelos ML;
- backtesting;
- gestión de riesgo;
- paper trading;
- ejecución demo;
- API FastAPI;
- persistencia;
- logging.

### MetaTrader 5

MT5 será la fuente y plataforma de ejecución:

- velas;
- ticks;
- spread;
- especificaciones de símbolos;
- cuenta demo;
- posiciones;
- órdenes;
- margen;
- ejecución.

### Crucix

Crucix será un servicio externo de contexto macro y OSINT:

- noticias;
- indicadores macroeconómicos;
- energía;
- metales;
- VIX;
- curva de rendimiento;
- conflictos;
- sanciones;
- eventos geopolíticos;
- detección de cambios;
- alertas.

Crucix no será utilizado como motor de ejecución, gestor de riesgo ni fuente
principal de precios M15 del broker.

### n8n

n8n será utilizado como orquestador:

- reentrenamiento programado;
- alertas;
- reportes;
- health checks;
- aprobación de modelos;
- conexión con Telegram y Discord.

n8n no contendrá la lógica crítica de lotaje, stop-loss o ejecución.

### Dashboard

El frontend debe mostrar:

- estado de MT5;
- estado de Crucix;
- estado del modelo;
- modo actual;
- señales;
- gráfico de precio;
- indicadores;
- contexto macro;
- operaciones;
- rendimiento;
- drawdown;
- logs relevantes;
- botón de kill switch.

---

# 4. Stack tecnológico

## Backend

- Python 3.12+.
- FastAPI.
- Pydantic.
- SQLAlchemy.
- Alembic.
- PostgreSQL.
- pytest.
- httpx.
- structlog o logging estructurado.

## MT5

- Paquete oficial `MetaTrader5`.
- Cliente aislado en `broker/mt5_client.py`.
- Mocks obligatorios para pruebas.
- Ningún test unitario debe conectarse a una cuenta real.

## Datos

- pandas o polars.
- numpy.
- pyarrow o Parquet para datasets históricos.
- pandas-ta o TA-Lib para indicadores.

## Machine learning

- scikit-learn.
- LightGBM.
- XGBoost opcional.
- joblib para persistencia inicial.
- MLflow o registry propio en una fase posterior.

## Frontend

- React.
- TypeScript.
- Vite.
- Tailwind CSS.
- Lightweight Charts, Recharts o Plotly.
- React Query o equivalente para datos del backend.

## Automatización

- n8n.
- Telegram.
- Discord opcional.
- Webhooks.

## Infraestructura

- Docker.
- Docker Compose.
- VPS Windows para MT5 + Python.
- PostgreSQL.
- Redis opcional para colas o locks.
- GitHub Actions.
- Backups.
- Health checks.

## Servicios opcionales

- Crucix como servicio Node.js independiente.
- NautilusTrader solo como posible evolución futura para backtesting o
  ejecución multi-venue. No es requisito inicial.

---

# 5. Estructura del repositorio

Crear esta estructura:

```text
intelligence-trading-platform/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
│
├── apps/
│   └── dashboard/
│       ├── package.json
│       ├── src/
│       └── tests/
│
├── src/
│   └── trading_system/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       │
│       ├── api/
│       │   ├── app.py
│       │   ├── dependencies.py
│       │   ├── routes_health.py
│       │   ├── routes_market.py
│       │   ├── routes_signals.py
│       │   ├── routes_trades.py
│       │   ├── routes_training.py
│       │   └── routes_controls.py
│       │
│       ├── broker/
│       │   ├── mt5_client.py
│       │   ├── market_data.py
│       │   ├── symbols.py
│       │   ├── account.py
│       │   ├── orders.py
│       │   └── positions.py
│       │
│       ├── macro/
│       │   ├── crucix_client.py
│       │   ├── macro_context.py
│       │   ├── macro_features.py
│       │   └── regime_classifier.py
│       │
│       ├── strategy/
│       │   ├── indicators.py
│       │   ├── features.py
│       │   ├── baseline.py
│       │   ├── signals.py
│       │   ├── filters.py
│       │   └── decision.py
│       │
│       ├── models/
│       │   ├── train.py
│       │   ├── predict.py
│       │   ├── validate.py
│       │   ├── registry.py
│       │   ├── schemas.py
│       │   └── artifacts/
│       │
│       ├── risk/
│       │   ├── position_sizing.py
│       │   ├── stops.py
│       │   ├── exposure.py
│       │   ├── limits.py
│       │   └── circuit_breaker.py
│       │
│       ├── execution/
│       │   ├── order_intent.py
│       │   ├── paper_executor.py
│       │   ├── demo_executor.py
│       │   └── reconciliation.py
│       │
│       ├── backtest/
│       │   ├── engine.py
│       │   ├── costs.py
│       │   ├── fills.py
│       │   ├── metrics.py
│       │   └── walk_forward.py
│       │
│       ├── storage/
│       │   ├── database.py
│       │   ├── models.py
│       │   ├── repositories.py
│       │   └── migrations/
│       │
│       ├── monitoring/
│       │   ├── logging.py
│       │   ├── metrics.py
│       │   └── health.py
│       │
│       └── workers/
│           ├── trading_loop.py
│           ├── training_worker.py
│           └── reporting_worker.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── safety/
│   ├── backtest/
│   ├── fixtures/
│   └── contract/
│
├── research/
│   ├── notebooks/
│   ├── datasets/
│   └── reports/
│
├── workflows/
│   └── n8n/
│       ├── retraining.json
│       ├── alerts.json
│       ├── daily-report.json
│       ├── health-monitor.json
│       └── model-approval.json
│
├── infra/
│   ├── docker/
│   ├── windows/
│   ├── monitoring/
│   └── backups/
│
└── docs/
    ├── architecture.md
    ├── risk-policy.md
    ├── model-policy.md
    ├── operations.md
    ├── api.md
    └── decisions/
```

---

# 6. Modos de funcionamiento

El sistema debe soportar:

```text
backtest
paper
demo
live
```

## Configuración inicial

```env
APP_ENV=development
TRADING_MODE=paper
LIVE_TRADING_ENABLED=false
ALLOW_DEMO_ORDERS=false

MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_PATH=

DEFAULT_SYMBOL=EURUSD
DEFAULT_TIMEFRAME=M15

MAX_RISK_PER_TRADE=0.005
MAX_DAILY_LOSS=0.02
MAX_OPEN_POSITIONS=1
MAX_SPREAD_POINTS=30

CRUCIX_BASE_URL=http://localhost:3117
CRUCIX_ENABLED=true

DATABASE_URL=sqlite:///./trading.db
N8N_BASE_URL=
```

## Reglas

- `paper` debe ser el modo por defecto.
- `demo` requiere una variable explícita.
- `live` debe estar bloqueado durante el MVP.
- Los secretos solo se cargan mediante variables de entorno.
- El sistema debe rechazar configuraciones ambiguas.
- El backend debe mostrar el modo actual en `/health`.
- El dashboard debe mostrar el modo actual permanentemente.

---

# 7. Integración con Crucix

Crucix se ejecutará como servicio separado.

## Arranque de Crucix

```bash
git clone https://github.com/calesthio/Crucix.git
cd Crucix
npm install
cp .env.example .env
npm run dev
```

Crucix debe exponer:

```text
GET /api/data
GET /api/health
GET /events
```

El adaptador Python debe consultar únicamente los endpoints necesarios.

## Contrato normalizado

El cliente Python debe transformar los datos de Crucix a este formato:

```python
class MacroContext(BaseModel):
    timestamp: datetime
    risk_regime: Literal["risk_on", "risk_off", "mixed", "unknown"]
    confidence: float
    vix: float | None
    vix_change_pct: float | None
    yield_curve: float | None
    oil_change_pct: float | None
    gold_change_pct: float | None
    credit_spread: float | None
    urgent_events: int
    conflict_events: int
    source_health: float
    data_stale: bool
```

Si Crucix está caído:

- no detener necesariamente el sistema completo;
- marcar el contexto como `unknown`;
- registrar el error;
- permitir solo la política configurada;
- por defecto, no abrir operaciones nuevas si el contexto macro es obligatorio.

## Uso macro

El contexto macro puede:

- filtrar señales;
- modificar la confianza;
- clasificar el régimen;
- generar alertas;
- enriquecer el dashboard;
- crear features para ML.

No puede:

- enviar órdenes;
- calcular lotaje;
- eliminar un stop-loss;
- superar los límites de riesgo.

---

# 8. Estrategia técnica inicial

Primero implementar una estrategia determinística sin machine learning.

## Indicadores

- EMA 20.
- EMA 50.
- EMA 200.
- RSI 14.
- MACD.
- ATR 14.
- ADX 14.
- Spread.
- Volumen cuando esté disponible.

## Señal LONG

Evaluar de forma configurable:

- EMA 50 > EMA 200.
- Precio sobre EMA 50.
- RSI recuperando desde una zona baja.
- MACD alcista.
- ADX por encima del mínimo.
- spread aceptable.
- contexto macro no bloquea.
- sin posición abierta para el símbolo.
- pérdida diaria no excedida.

## Señal SHORT

Solo si está soportado por la cuenta y el broker:

- EMA 50 < EMA 200.
- Precio bajo EMA 50.
- RSI bajista.
- MACD bajista.
- ADX por encima del mínimo.
- spread aceptable.
- contexto macro no bloquea.
- sin posición abierta.
- pérdida diaria no excedida.

## HOLD

Devolver `HOLD` cuando:

- la vela no está cerrada;
- faltan datos;
- los indicadores no están preparados;
- el spread es excesivo;
- MT5 está desconectado;
- los datos están obsoletos;
- el contexto macro es inválido;
- la señal técnica y macro se contradicen;
- el riesgo está bloqueado;
- existe una posición incompatible.

---

# 9. Machine learning

## Orden obligatorio

1. Baseline determinística.
2. Backtesting reproducible.
3. Paper trading.
4. Features.
5. Baseline ML sencilla.
6. Walk-forward validation.
7. Comparación contra baseline.
8. Activación opcional como filtro.

No comenzar con reinforcement learning ni redes neuronales complejas.

## Features técnicas

```text
return_1
return_3
return_5
return_10
ema_20
ema_50
ema_200
distance_to_ema_50
distance_to_ema_200
rsi
macd
macd_signal
macd_hist
atr
atr_percent
adx
spread
hour
day_of_week
```

## Features macro

```text
vix
vix_change_pct
yield_curve
oil_change_pct
gold_change_pct
credit_spread
urgent_events
conflict_events
source_health
risk_regime
```

## Etiquetas

La etiqueta debe representar la operación real.

Preferencia:

```text
1 = take-profit alcanzado antes que stop-loss
0 = stop-loss alcanzado antes que take-profit
```

Alternativa:

```text
retorno futuro a N velas
```

Documentar siempre:

- horizonte;
- stop;
- take-profit;
- timeframe;
- costes;
- reglas de exclusión.

## Validación

Nunca usar una división aleatoria simple para series temporales.

Usar:

```text
train
validation
test
walk-forward
```

El modelo debe compararse contra:

- estrategia baseline;
- buy-and-hold cuando sea aplicable;
- modelo ingenuo;
- modelo anterior.

## Métricas

Medir:

- expectancy;
- profit factor;
- drawdown;
- Sharpe;
- Sortino;
- win rate;
- operaciones;
- estabilidad temporal;
- sensibilidad a costes;
- rendimiento por régimen macro.

Accuracy no es suficiente.

## Registry

Cada modelo debe guardar:

```json
{
  "version": "model-v0001",
  "symbol": "EURUSD",
  "timeframe": "M15",
  "features": [],
  "train_start": "...",
  "train_end": "...",
  "validation_start": "...",
  "validation_end": "...",
  "test_start": "...",
  "test_end": "...",
  "metrics": {},
  "costs": {},
  "status": "candidate"
}
```

Estados permitidos:

```text
candidate
validated
approved
active
rejected
retired
```

Un modelo nuevo nunca se activa automáticamente solo por mejorar el beneficio
total.

---

# 10. Gestión de riesgo

La gestión de riesgo debe estar completamente separada de:

- la estrategia;
- el modelo;
- el LLM;
- Crucix;
- n8n.

## Riesgo por operación

Inicialmente:

```text
0.25% - 0.5% del capital
```

## Cálculo conceptual

```text
riesgo_monetario = capital × riesgo_porcentaje

distancia_stop = abs(entry - stop_loss)

pérdida_por_lote =
    distancia_stop × valor_por_punto_del_lote

lotes =
    riesgo_monetario / pérdida_por_lote
```

Validar mediante las propiedades reales del símbolo de MT5:

- tick value;
- tick size;
- point;
- contract size;
- volumen mínimo;
- volumen máximo;
- volumen step;
- moneda de la cuenta;
- margen;
- apalancamiento.

## Límites

Implementar:

```text
max_risk_per_trade
max_daily_loss
max_open_positions
max_symbol_exposure
max_consecutive_losses
max_spread
max_slippage
max_trades_per_day
```

## Circuit breaker

Bloquear nuevas operaciones cuando:

- se supera la pérdida diaria;
- MT5 está desconectado;
- una posición no puede reconciliarse;
- se detecta una orden duplicada;
- el modelo está vencido;
- los datos están obsoletos;
- el spread es excesivo;
- fallan demasiadas llamadas;
- el sistema se reinicia con estado inconsistente.

---

# 11. Ejecución

## Paper executor

Debe:

- simular fills;
- simular spread;
- aplicar costes;
- guardar órdenes;
- guardar posiciones;
- aplicar stop-loss y take-profit;
- producir las mismas interfaces que el executor demo.

## Demo executor

Debe:

- validar que la cuenta sea demo;
- validar el modo;
- validar la orden;
- consultar el estado real;
- evitar duplicados;
- enviar la orden;
- guardar respuesta sanitizada;
- reconciliar posiciones;
- manejar timeouts;
- reintentar únicamente después de consultar el estado real.

## Order intent

Toda operación debe convertirse primero en una intención:

```python
class OrderIntent(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    risk_amount: float
    strategy_version: str
    model_version: str | None
    mode: Literal["paper", "demo"]
    reason: str
```

El executor no debe aceptar una orden que no venga acompañada de:

- stop-loss;
- volumen validado;
- riesgo;
- modo permitido;
- señal válida.

---

# 12. Backtesting

El backtest debe incluir:

- velas cerradas;
- spread;
- comisión;
- slippage;
- stop-loss;
- take-profit;
- swaps cuando aplique;
- precisión;
- volumen mínimo;
- retraso de ejecución;
- límites del broker cuando estén disponibles.

## Métricas obligatorias

- beneficio neto;
- drawdown máximo;
- profit factor;
- expectancy;
- Sharpe;
- Sortino;
- win rate;
- pérdida promedio;
- ganancia promedio;
- pérdidas consecutivas;
- resultado mensual;
- resultado anual;
- resultado por sesión;
- resultado por símbolo;
- tiempo expuesto;
- operaciones rechazadas;
- motivo de salida.

No aprobar una estrategia solo por:

- beneficio total;
- win rate;
- una muestra pequeña;
- una única configuración;
- un solo periodo;
- un solo símbolo.

---

# 13. Dashboard

El dashboard debe mostrar:

## Estado

- modo actual;
- conexión MT5;
- conexión Crucix;
- conexión PostgreSQL;
- modelo activo;
- última vela;
- última señal;
- estado del circuit breaker.

## Mercado

- gráfico de precio;
- EMA;
- RSI;
- MACD;
- ATR;
- spread;
- contexto macro;
- régimen risk-on/risk-off.

## Señal

- LONG/SHORT/HOLD;
- confianza;
- razones técnicas;
- razones macro;
- entry;
- stop-loss;
- take-profit;
- lotaje;
- riesgo;
- modelo utilizado.

## Operaciones

- abiertas;
- cerradas;
- ganancias;
- pérdidas;
- drawdown;
- exposición;
- métricas.

## Operaciones peligrosas

El dashboard debe exigir confirmación para:

- activar demo;
- activar un modelo;
- ejecutar kill switch;
- cambiar límites de riesgo.

Nunca incluir un botón de live durante el MVP.

---

# 14. API FastAPI

Crear inicialmente:

```text
GET  /health
GET  /status
GET  /market/{symbol}
GET  /macro/context
GET  /signals/latest
GET  /trades
GET  /positions
GET  /performance
GET  /models
GET  /models/active

POST /training/run
POST /models/{version}/approve
POST /models/{version}/reject
POST /system/kill-switch
POST /system/resume
```

## `/health`

Debe informar:

```json
{
  "status": "ok",
  "mode": "paper",
  "mt5_connected": true,
  "crucix_connected": true,
  "database_connected": true,
  "model_active": "baseline-v001",
  "circuit_breaker": false
}
```

Nunca exponer secretos en la API.

---

# 15. n8n

Crear estos workflows:

## Retraining

```text
Schedule Trigger
→ POST /training/run
→ esperar resultado
→ GET /training/status
→ comparar métricas
→ Telegram/Discord
→ solicitar aprobación
```

## Health monitor

```text
Cada 5 minutos
→ GET /health
→ si falla MT5, Crucix o base de datos:
   enviar alerta
→ si el sistema no responde:
   alertar
```

## Daily report

```text
Cada día
→ GET /performance
→ GET /trades
→ GET /models/active
→ generar reporte
→ enviar Telegram/Discord
```

## Model approval

```text
Nuevo modelo candidate
→ enviar métricas
→ aprobación manual
→ POST /models/{version}/approve
```

n8n no debe enviar órdenes directamente durante el MVP.

---

# 16. Despliegue

## Desarrollo local

```text
Python API
Crucix local
PostgreSQL local
Dashboard local
n8n local opcional
MT5 local en demo
```

## VPS

```text
VPS Windows
├── MetaTrader 5
├── trading-system Python
├── PostgreSQL
├── Crucix
├── n8n opcional
└── backups y monitoreo
```

El sistema debe reiniciarse automáticamente.

Implementar:

- logs persistentes;
- backup de base de datos;
- health checks;
- sincronización horaria;
- variables de entorno;
- rotación de logs;
- acceso remoto seguro;
- kill switch;
- restauración de backups.

---

# 17. Seguridad

Nunca guardar en Git:

```text
.env
MT5_PASSWORD
MT5_LOGIN real
LLM_API_KEY
TELEGRAM_BOT_TOKEN
DISCORD_BOT_TOKEN
DISCORD_WEBHOOK_URL
credenciales del VPS
```

Crear solo:

```env
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
LLM_API_KEY=
TELEGRAM_BOT_TOKEN=
DISCORD_BOT_TOKEN=
```

## Reglas

- Sanitizar logs.
- Validar todo input externo.
- Validar JSON de LLM.
- No aceptar URLs arbitrarias sin validación.
- No ejecutar comandos derivados de mensajes.
- No permitir que un LLM llame directamente a MT5.
- No permitir que n8n llame directamente a `order_send`.
- Usar autenticación para la API.
- Añadir rate limiting si se expone externamente.
- No exponer el dashboard sin autenticación en producción.

---

# 18. Fases de implementación

## Fase 0: arquitectura

Crear:

```text
README.md
docs/architecture.md
docs/risk-policy.md
docs/model-policy.md
docs/implementation-plan.md
docs/progress.md
```

No implementar trading todavía.

Criterios:

- arquitectura documentada;
- módulos definidos;
- contratos definidos;
- riesgos documentados;
- live bloqueado.

## Fase 1: configuración y estructura

Implementar:

- `pyproject.toml`;
- configuración;
- `.env.example`;
- logging;
- CLI;
- modos de operación;
- pruebas iniciales.

## Fase 2: integración MT5

Implementar:

- cliente MT5;
- health check;
- símbolos;
- cuenta;
- velas;
- ticks;
- spread;
- posiciones;
- mocks.

No enviar órdenes.

## Fase 3: integración Crucix

Implementar:

- `crucix_client.py`;
- contrato `MacroContext`;
- health check;
- timeout;
- fallback;
- normalización;
- pruebas con fixtures.

## Fase 4: estrategia baseline

Implementar:

- indicadores;
- features técnicas;
- señales;
- filtros;
- contexto macro;
- LONG/SHORT/HOLD;
- pruebas unitarias.

## Fase 5: riesgo

Implementar:

- lotaje;
- stops;
- take-profit;
- límites;
- exposición;
- circuit breaker;
- kill switch;
- pruebas de seguridad.

## Fase 6: backtesting

Implementar:

- engine;
- fills;
- costes;
- slippage;
- métricas;
- reportes;
- walk-forward.

## Fase 7: paper trading

Implementar:

- loop de velas cerradas;
- paper executor;
- persistencia;
- reconciliación simulada;
- reportes.

## Fase 8: machine learning

Implementar:

- features técnicas y macro;
- labels;
- train/validation/test;
- LightGBM;
- predicción;
- registry;
- walk-forward;
- comparación contra baseline.

## Fase 9: API y dashboard

Implementar:

- FastAPI;
- autenticación;
- endpoints;
- React;
- gráficos;
- señales;
- operaciones;
- métricas;
- macro context.

## Fase 10: n8n

Implementar:

- retraining;
- alertas;
- reportes;
- health monitor;
- model approval.

## Fase 11: VPS y cuenta demo

Implementar:

- instalación;
- servicios;
- reinicio automático;
- backups;
- monitoreo;
- demo MT5;
- validación de desconexiones.

## Fase 12: evaluación

No pasar a dinero real salvo que:

- el backtest sea reproducible;
- exista resultado fuera de muestra;
- walk-forward sea razonable;
- paper trading sea estable;
- demo sea estable;
- los costes estén incluidos;
- el circuit breaker haya sido probado;
- el auditor no encuentre problemas críticos.

---

# 19. Agentes de Claude

Si el entorno permite múltiples agentes, dividir así:

## Architect Agent

- define contratos;
- revisa arquitectura;
- mantiene decisiones;
- evita duplicación.

## MT5 Agent

- integración MT5;
- datos;
- cuenta;
- símbolos;
- posiciones;
- órdenes demo.

## Crucix Agent

- cliente API;
- normalización;
- contexto macro;
- health;
- fallback.

## Strategy Agent

- indicadores;
- baseline;
- señales;
- filtros.

## Risk Agent

- lotaje;
- stop-loss;
- take-profit;
- límites;
- circuit breaker.

## Backtest Agent

- engine;
- costes;
- fills;
- métricas;
- walk-forward.

## ML Agent

- features;
- labels;
- entrenamiento;
- validación;
- registry.

## Backend Agent

- FastAPI;
- autenticación;
- persistencia;
- endpoints.

## Frontend Agent

- dashboard;
- gráficos;
- estado;
- operaciones.

## Automation Agent

- n8n;
- Telegram;
- Discord;
- reportes.

## DevOps Agent

- Docker;
- VPS;
- backups;
- logs;
- health checks.

## Security Auditor Agent

- revisa secretos;
- revisa órdenes;
- revisa riesgo;
- revisa duplicados;
- revisa modo live;
- revisa validación de LLM;
- no implementa funcionalidades nuevas.

No permitir que dos agentes editen simultáneamente el mismo archivo crítico.

---

# 20. Reglas de trabajo para Claude

Antes de modificar código:

1. Leer este `CLAUDE.md`.
2. Inspeccionar el repositorio.
3. Identificar la fase actual.
4. Explicar el plan.
5. Identificar archivos afectados.
6. Identificar riesgos.
7. Implementar cambios pequeños.
8. Añadir pruebas.
9. Ejecutar pruebas.
10. Revisar seguridad.
11. Actualizar documentación.
12. Actualizar `docs/progress.md`.

No hacer cambios masivos sin aprobación.

No borrar código de seguridad.

No ocultar errores.

No inventar resultados.

No declarar rentabilidad sin pruebas fuera de muestra.

No avanzar de fase si fallan los criterios de aceptación.

Cuando exista ambigüedad, elegir la opción más segura y documentar la
suposición.

---

# 21. Primer prompt para Claude

Lee completamente este archivo.

No implementes código todavía.

Actúa como arquitecto principal del proyecto.

Haz lo siguiente:

1. Inspecciona el repositorio actual.
2. Crea o actualiza:
   - `docs/architecture.md`
   - `docs/implementation-plan.md`
   - `docs/progress.md`
3. Define los contratos entre:
   - MT5;
   - Crucix;
   - strategy;
   - models;
   - risk;
   - execution;
   - backtest;
   - storage;
   - API;
   - frontend;
   - n8n.
4. Divide el proyecto en tareas.
5. Identifica tareas paralelizables.
6. Define criterios de aceptación por fase.
7. Identifica riesgos técnicos y financieros.
8. Mantén `live trading` bloqueado.
9. No conectes todavía con MT5.
10. No entrenes modelos.
11. No envíes órdenes.

Al terminar, muestra:

- arquitectura propuesta;
- árbol de archivos;
- plan por fases;
- agentes recomendados;
- dependencias;
- riesgos;
- primer sprint;
- comandos de prueba.