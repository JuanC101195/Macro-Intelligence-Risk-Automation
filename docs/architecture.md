# Arquitectura — Intelligence Trading Platform

> Estado: Fase 0 (diseño). Nada de esto está implementado todavía.
> Fuente de verdad de requisitos: `CLAUDE.md`. Decisiones: `docs/decisions/`.

## 1. Principios

1. **Seguridad antes que rentabilidad.** Primero se demuestra que el sistema es técnicamente correcto; la ventaja estadística se evalúa después y fuera de muestra.
2. **Un solo camino hacia una orden.** `Signal → RiskEngine → OrderIntent → Executor`. Ningún otro módulo (estrategia, ML, Crucix, n8n, API, LLM) puede crear un `OrderIntent` ni llamar a `order_send`.
3. **Live bloqueado.** No hay rama de código que ejecute en cuenta real. El modo `live` existe en el enum solo para que el validador lo rechace de forma explícita.
4. **Fallar cerrado.** Ante datos faltantes, obsoletos, ambiguos o errores, el resultado es `HOLD` o bloqueo, nunca una orden.
5. **Mismo código en backtest, paper y demo.** Estrategia y riesgo son idénticos; solo cambian la fuente de datos y el executor.
6. **Determinismo y trazabilidad.** Cada señal, decisión de riesgo y orden se persiste con versión de estrategia, versión de modelo y razones.
7. **Todo en UTC.** La hora del servidor MT5 se convierte a UTC en la frontera (`broker/market_data.py`).

## 2. Vista de componentes

```text
                    Crucix (Node, servicio externo)
                             │ HTTP GET /api/data, /api/health
                             ▼
 MT5 terminal ──► broker/ ──► market data ─┐   macro/ ──► MacroContext
   (Windows)       (único                  │                    │
                   import de               ▼                    ▼
                   MetaTrader5)      strategy/ (indicadores, features, baseline)
                                           │ Signal (LONG/SHORT/HOLD + SL/TP propuestos)
                                           ▼
                                     models/ (opcional, filtro ML) ──► Signal ajustada
                                           │
                                           ▼
                                     risk/ RiskEngine + CircuitBreaker
                                           │ RiskDecision ── OrderIntent (único productor)
                                           ▼
                                     execution/ PaperExecutor | DemoExecutor
                                           │ ExecutionResult
                                           ▼
                                     storage/ (SQLite dev / PostgreSQL)
                                           │
                        ┌──────────────────┼───────────────────┐
                        ▼                  ▼                   ▼
                    api/ FastAPI      workers/ loop        monitoring/
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
       React dashboard           n8n (solo API; nunca órdenes)
```

### Reglas de dependencia entre paquetes

| Paquete | Puede importar | No puede importar |
|---------|----------------|-------------------|
| `config` | — | nada del dominio |
| `broker` | `config`, `monitoring` | `strategy`, `risk`, `execution` |
| `macro` | `config`, `monitoring` | `broker`, `risk`, `execution` |
| `strategy` | contratos de `broker` y `macro` (tipos) | `risk`, `execution`, `broker.mt5_client` |
| `models` | `strategy` (features) | `risk`, `execution` |
| `risk` | `config`, tipos de `broker` y `strategy`, `execution.order_intent` (solo tipos) | executors (`paper_executor`, `demo_executor`), `macro.crucix_client`, `models` |
| `execution` | `broker` (tipos) | `strategy`, `models`, `macro` |
| `backtest` | `strategy`, `risk`, `execution.paper_executor` | `broker.mt5_client` |
| `api` | servicios y repositorios | `broker.orders` (nunca envía órdenes directamente) |

`tests/safety/test_architecture.py` verifica estas reglas sobre el código (análisis AST de imports). También verifica que `MetaTrader5` solo se importe en `broker/mt5_client.py` y que `order_send` no aparezca en ningún archivo antes de la Fase 11.

`OrderIntent` vive en `execution/order_intent.py` (ruta de `CLAUDE.md`). Ese módulo contiene **solo tipos**, para que `risk/` pueda construir intenciones sin depender de ningún executor.

## 3. Modos de operación

| Modo | Datos | Executor | Requisitos | Estado MVP |
|------|-------|----------|------------|------------|
| `backtest` | Históricos (Parquet) | `SimulatedBroker` + fills simulados | — | permitido |
| `paper` | MT5 en vivo (o mock) | `PaperExecutor` | default | permitido |
| `demo` | MT5 en vivo | `DemoExecutor` | `ALLOW_DEMO_ORDERS=true` **y** `account.trade_mode == DEMO` comprobado en runtime | permitido tras Fase 11 |
| `live` | — | — | — | **rechazado al arrancar** |

### Validación de configuración (fail-fast)

El arranque aborta con error si:

- `TRADING_MODE=live`;
- `LIVE_TRADING_ENABLED=true`;
- `TRADING_MODE=demo` y `ALLOW_DEMO_ORDERS` ≠ `true`;
- `ALLOW_DEMO_ORDERS=true` y `TRADING_MODE` ≠ `demo` (ambigüedad);
- `MAX_RISK_PER_TRADE > 0.005` o `MAX_DAILY_LOSS > 0.02` (techos duros del MVP);
- `CRUCIX_ENABLED=false` y `MACRO_REQUIRED=true`;
- `APP_ENV=production` sin `API_KEY` definido.

Además, el `DemoExecutor` vuelve a comprobar en cada orden que la cuenta conectada es demo. Si MT5 reporta `ACCOUNT_TRADE_MODE_REAL`, activa el circuit breaker y no envía nada.

## 4. Flujo principal (por vela cerrada)

```text
1. trading_loop espera cierre de vela M15 (+ margen de 2–5 s)
2. broker: obtiene últimas N velas cerradas + tick actual + SymbolSpec
3. validación: vela cerrada, sin huecos, no obsoleta (≤ 1 timeframe de retraso)
4. macro: MacroContext desde caché (refresco cada X min; si falla → unknown)
5. strategy.evaluate(...)          → Signal
6. models.filter(signal, features) → Signal (opcional; solo puede bajar confianza o pasar a HOLD)
7. risk.evaluate(signal, account, spec, exposure) → RiskDecision
8. si aprobada: executor.submit(intent) → ExecutionResult
9. storage: persiste Signal, RiskDecision, OrderIntent, ExecutionResult
10. monitoring: logs estructurados + métricas; eventos críticos → n8n vía API/health
```

El paso 6 nunca puede convertir un `HOLD` en `LONG`/`SHORT` ni modificar SL, TP o volumen.

## 5. Contratos

Los contratos se escriben como modelos Pydantic (datos) y `typing.Protocol` (comportamiento).
Viven en el módulo indicado y son la única forma de comunicarse entre paquetes.

### 5.1 Tipos comunes (`trading_system/domain.py`)

```python
class TradingMode(StrEnum): BACKTEST="backtest"; PAPER="paper"; DEMO="demo"; LIVE="live"
class Timeframe(StrEnum): M1="M1"; M5="M5"; M15="M15"; H1="H1"; H4="H4"; D1="D1"
class Side(StrEnum): LONG="LONG"; SHORT="SHORT"; HOLD="HOLD"
```

### 5.2 Broker / MT5 (`broker/`)

Único lugar donde se importa `MetaTrader5`. Todo lo demás usa el protocolo.

```python
class Bar(BaseModel):
    time: datetime            # apertura de la vela, UTC
    open: float; high: float; low: float; close: float
    tick_volume: int
    spread_points: int
    real_volume: int | None

class Tick(BaseModel):
    time: datetime; bid: float; ask: float; spread_points: int

class SymbolSpec(BaseModel):
    symbol: str
    digits: int; point: float
    tick_size: float; tick_value: float      # en la divisa de la cuenta
    contract_size: float
    volume_min: float; volume_max: float; volume_step: float
    stops_level_points: int; freeze_level_points: int
    currency_base: str; currency_profit: str; currency_margin: str
    trade_allowed: bool; short_allowed: bool

class AccountInfo(BaseModel):
    login_masked: str          # p. ej. "****1234"; el login completo nunca sale del broker
    server: str
    trade_mode: Literal["demo", "contest", "real"]
    currency: str
    balance: float; equity: float; margin: float; margin_free: float
    leverage: int

class Position(BaseModel):
    ticket: int; symbol: str; side: Literal["buy", "sell"]
    volume: float; open_price: float; stop_loss: float | None; take_profit: float | None
    open_time: datetime; profit: float; comment: str   # comment lleva el intent_id

class MarketDataSource(Protocol):
    def is_connected(self) -> bool: ...
    def account_info(self) -> AccountInfo: ...
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...
    def closed_bars(self, symbol: str, tf: Timeframe, count: int) -> list[Bar]: ...
    def last_tick(self, symbol: str) -> Tick: ...
    def positions(self, symbol: str | None = None) -> list[Position]: ...
    def calc_margin(self, symbol: str, side: str, volume: float, price: float) -> float: ...
    def calc_profit(self, symbol: str, side: str, volume: float,
                    price_open: float, price_close: float) -> float: ...

class OrderGateway(Protocol):       # solo lo usa DemoExecutor
    def send(self, request: "BrokerOrderRequest") -> "BrokerOrderResponse": ...
    def find_by_comment(self, intent_id: str) -> list[Position]: ...
```

Implementaciones: `Mt5Client` (real), `FakeMt5` (tests), `HistoricalDataSource` (backtest).

**Hora del servidor.** MT5 entrega timestamps en hora local del servidor, no en UTC. La diferencia se **configura** (`MT5_SERVER_UTC_OFFSET_MINUTES`); no se deduce sola. Un tick viejo cuya antigüedad se acerca a un múltiplo de 30 min parece fresco y daría una diferencia falsa pero creíble (lo detectó un test). Con el mercado abierto, los ticks frescos solo se usan para **verificar** el valor configurado: si no coincide (por ejemplo, el broker cambió al horario de verano), el cliente se detiene. Sin valor configurado, no lee datos (fail-closed).

`Bar` está en precio **bid**. Para la entrada se usa el ask y para disparar SL/TP en un SHORT se usa `bid + spread` (detalle en `risk-policy.md` §2).

### 5.3 Crucix / macro (`macro/`)

```python
class MacroContext(BaseModel):          # contrato de CLAUDE.md §7
    timestamp: datetime
    risk_regime: Literal["risk_on", "risk_off", "mixed", "unknown"]
    confidence: float                    # 0..1
    vix: float | None; vix_change_pct: float | None
    yield_curve: float | None
    oil_change_pct: float | None; gold_change_pct: float | None
    credit_spread: float | None
    urgent_events: int; conflict_events: int
    source_health: float                 # 0..1
    data_stale: bool

class MacroProvider(Protocol):
    def current(self) -> MacroContext: ...   # nunca lanza excepción; ante fallo devuelve unknown
    def healthy(self) -> bool: ...
```

- `CrucixClient` usa solo `GET /api/health` y `GET /api/data` (timeout 5 s, 2 reintentos con backoff).
- `GET /events` (SSE) queda fuera del MVP.
- El mapeo de la respuesta cruda de Crucix a `MacroContext` está **pendiente de verificar** contra el servicio real (Fase 3). Los nombres de campos de Crucix no se asumen.
- `data_stale = now - timestamp > MACRO_MAX_AGE` (default 30 min).
- Política (`MACRO_REQUIRED=false` en MVP, ADR 0001):
  - `unknown` o `data_stale` → la señal sigue, con `confidence × MACRO_UNKNOWN_PENALTY` (default 0.8) y razón registrada.
  - `risk_off` con señal LONG en pares risk-on, o contradicción explícita → `HOLD` (configurable).
  - Si `MACRO_REQUIRED=true` → `unknown`/`stale` ⇒ `HOLD`.
- **Histórico macro:** Crucix entrega el estado *actual*, no series históricas consultables por fecha. Por eso:
  - desde la Fase 3 se guarda cada `MacroContext` en `macro_snapshots` (cada 15 min), y ese es el único histórico macro que tendrá el sistema;
  - en backtest, antes de la primera snapshot el contexto es `unknown` (no se inventa);
  - las features macro del ML solo pueden entrenarse sobre el periodo grabado, así que empezar a grabar pronto es lo que define cuándo serán utilizables;
  - en backtest se usa la última snapshot con `timestamp ≤ cierre de la vela` (sin look-ahead).

### 5.4 Strategy (`strategy/`)

```python
class Signal(BaseModel):
    signal_id: str                       # uuid
    symbol: str; timeframe: Timeframe
    bar_time: datetime                   # vela cerrada que la originó
    side: Side
    confidence: float                    # 0..1
    technical_score: int                 # 0..100
    reasons: list[str]                   # condiciones cumplidas
    hold_reasons: list[str]              # si side == HOLD
    macro_regime: str
    entry_ref: float | None              # precio de referencia (close o ask/bid)
    stop_loss: float | None              # propuesto por ATR
    take_profit: float | None
    strategy_version: str                # "baseline-v001"
    model_version: str | None

class Strategy(Protocol):
    version: str
    def evaluate(self, bars: Sequence[Bar], tick: Tick, spec: SymbolSpec,
                 macro: MacroContext, state: "MarketState") -> Signal: ...
```

- `MarketState` incluye si hay posición abierta en el símbolo y si riesgo está bloqueado (solo para generar `HOLD` explicativo; la autoridad sigue siendo `risk/`).
- La estrategia **propone** SL/TP (p. ej. SL = 1.5×ATR, TP = 2×SL); **no calcula volumen**.
- Es una función pura sobre sus entradas: mismo input ⇒ mismo output (testeable con fixtures).

### 5.5 Models (`models/`)

```python
class ModelRecord(BaseModel):            # CLAUDE.md §9 Registry
    version: str; symbol: str; timeframe: Timeframe
    features: list[str]
    train_start: datetime; train_end: datetime
    validation_start: datetime; validation_end: datetime
    test_start: datetime; test_end: datetime
    label_spec: dict                     # horizonte, SL, TP, costes, exclusiones
    metrics: dict; costs: dict
    status: Literal["candidate","validated","approved","active","rejected","retired"]
    artifact_sha256: str
    expires_at: datetime                 # modelo vencido ⇒ circuit breaker / ignorar

class SignalFilter(Protocol):
    version: str
    def adjust(self, signal: Signal, features: Mapping[str, float]) -> Signal: ...
```

`adjust` solo puede bajar `confidence` o pasar a `HOLD`. Transiciones de estado: ver `docs/model-policy.md`.

### 5.6 Risk (`risk/`)

```python
class RiskLimits(BaseModel):
    max_risk_per_trade: float = 0.005     # techo duro 0.005
    max_daily_loss: float = 0.02
    max_open_positions: int = 1
    max_symbol_exposure: int = 1
    max_consecutive_losses: int = 3
    max_spread_points: int = 30
    max_slippage_points: int = 10
    max_trades_per_day: int = 5

class ExposureSnapshot(BaseModel):
    open_positions: list[Position]
    realized_pnl_today: float; unrealized_pnl: float
    consecutive_losses: int; trades_today: int
    day_start_equity: float

class OrderIntent(BaseModel):            # CLAUDE.md §11 + extensión ADR 0001
    intent_id: str                       # sha256(strategy_version|symbol|tf|bar_time|side)[:16]
    signal_id: str
    signal_bar_time: datetime
    symbol: str
    side: Literal["buy", "sell"]
    entry_price: float
    stop_loss: float                     # obligatorio, nunca None
    take_profit: float
    volume: float                        # ya redondeado a volume_step, dentro de [min,max]
    risk_amount: float                   # en divisa de la cuenta
    strategy_version: str
    model_version: str | None
    mode: Literal["backtest", "paper", "demo"]   # "backtest" añadido (ADR 0001 #11)
    reason: str

class RiskDecision(BaseModel):
    approved: bool
    intent: OrderIntent | None
    rejections: list[str]                # p. ej. "spread_too_wide", "daily_loss_hit"
    risk_percent: float | None

class RiskEngine(Protocol):
    def evaluate(self, signal: Signal, account: AccountInfo, spec: SymbolSpec,
                 tick: Tick, exposure: ExposureSnapshot) -> RiskDecision: ...

class CircuitBreaker(Protocol):
    def is_open(self) -> bool: ...                     # open = bloqueado
    def trip(self, reason: str, source: str) -> None: ...
    def reset(self, operator: str) -> None: ...        # solo manual (API con confirmación)
    def state(self) -> "BreakerState": ...
```

- `RiskEngine` es el **único** constructor de `OrderIntent` (el constructor se marca como interno y un test de seguridad lo verifica).
- El estado del circuit breaker y del kill switch se persiste: tras un reinicio arranca en el último estado y, si hay inconsistencia, arranca **abierto**.
- Fórmula de lotaje y ejemplos (incluido USDJPY): `docs/risk-policy.md`.

### 5.7 Execution (`execution/`)

```python
class ExecutionResult(BaseModel):
    intent_id: str
    status: Literal["filled", "rejected", "duplicate", "error", "unknown"]
    broker_ticket: int | None
    fill_price: float | None; fill_time: datetime | None
    slippage_points: float | None
    commission: float; swap: float
    message: str                          # respuesta sanitizada

class Executor(Protocol):
    mode: Literal["paper", "demo"]
    def submit(self, intent: OrderIntent) -> ExecutionResult: ...
    def close(self, ticket: int, reason: str) -> ExecutionResult: ...
    def sync(self) -> list[Position]: ...                 # reconciliación
```

Reglas comunes (verificadas por tests de seguridad):

- Rechaza `intent.mode` distinto de `self.mode` y cualquier `mode` = `live`.
- Rechaza si el circuit breaker está abierto.
- Rechaza `intent_id` ya persistido (idempotencia) ⇒ `status="duplicate"` y dispara el breaker.
- `DemoExecutor`: comprueba `account.trade_mode == "demo"`, escribe `intent_id` en el `comment` de la orden (≤ 31 caracteres) y usa un `magic` number fijo del sistema. Ante timeout, **consulta posiciones y deals por `magic` + comment + símbolo + hora antes de reintentar**. Algunos brokers reescriben el comment, así que no se depende solo de él: también se guarda localmente el mapeo `intent_id → ticket` en cuanto llega la respuesta.
- `PaperExecutor` simula fills a bid/ask + slippage configurable + comisión, y aplica SL/TP con los high/low de cada vela posterior (peor caso si ambos se tocan en la misma vela: SL primero).

### 5.8 Backtest (`backtest/`)

```python
class CostModel(BaseModel):
    spread_mode: Literal["historical", "fixed"]; fixed_spread_points: int | None
    commission_per_lot: float; slippage_points: float
    swap_long: float; swap_short: float
    execution_delay_bars: int = 0         # 0 = abre en open de la vela siguiente

class BacktestConfig(BaseModel):
    symbols: list[str]; timeframe: Timeframe
    start: datetime; end: datetime
    initial_equity: float; account_currency: str
    strategy_version: str; risk_limits: RiskLimits; costs: CostModel
    data_hash: str                        # hash del dataset, para reproducibilidad
    seed: int

class BacktestReport(BaseModel):
    config: BacktestConfig
    trades: list["ClosedTrade"]
    metrics: dict                         # lista obligatoria en CLAUDE.md §12
    rejected: list[RiskDecision]
    equity_curve: list[tuple[datetime, float]]
```

El engine reutiliza `Strategy`, `RiskEngine` y la lógica de fills de `PaperExecutor`. Las señales se generan con la vela `t` cerrada y se ejecutan en la apertura de `t+1` (sin look-ahead).

### 5.9 Storage (`storage/`)

Tablas (SQLAlchemy + Alembic):

| Tabla | Contenido |
|-------|-----------|
| `signals` | `Signal` completo, JSON de razones |
| `risk_decisions` | decisión, rechazos, `signal_id` |
| `order_intents` | `OrderIntent`; `intent_id` **UNIQUE** (respaldo de idempotencia) |
| `executions` | `ExecutionResult` |
| `trades` | operaciones cerradas: entrada, salida, P&L, motivo de salida, costes |
| `position_snapshots` | resultado de cada `sync()` |
| `macro_snapshots` | `MacroContext` por consulta |
| `model_registry` | `ModelRecord` + historial de cambios de estado |
| `system_events` | breaker trip/reset, kill switch, cambios de modo y de límites, con operador |
| `backtest_runs` | config, hash de datos, métricas |

Velas históricas: Parquet en `research/datasets/` (no en la BD), particionado por símbolo/timeframe/año.

Acceso solo vía repositorios (`SignalRepository`, `TradeRepository`, ...). La API no ejecuta SQL directamente.

### 5.10 API (`api/`)

- Autenticación: header `X-API-Key` en todos los endpoints salvo `GET /health` (que no devuelve datos sensibles).
- Endpoints: los de `CLAUDE.md` §14, más `GET /training/status` (lo usa el workflow de retraining).
- Endpoints peligrosos (`/system/kill-switch`, `/system/resume`, `/models/{v}/approve`) exigen body `{"confirm": true, "operator": "<nombre>", "reason": "..."}` y quedan en `system_events`.
- **No existe** ningún endpoint que cree órdenes, cambie a `live` ni modifique el volumen de una orden.
- Respuestas Pydantic; nunca se serializan `Settings` ni credenciales.
- `/health`: contrato de `CLAUDE.md` §14, añadiendo `last_bar_time` y `version`.

### 5.11 Frontend (`apps/dashboard`)

- Solo consume la API. No tiene lógica de riesgo ni cálculo de lotaje.
- Banner permanente con el modo (paper = azul, demo = ámbar). No existe botón de live.
- Acciones peligrosas: modal de confirmación que escribe el nombre del símbolo o "KILL" + motivo.
- Polling con React Query (5–15 s); SSE/WebSocket queda para una fase posterior.

### 5.12 n8n (`workflows/n8n`)

- Allowlist de endpoints que puede llamar: `GET /health`, `GET /performance`, `GET /trades`, `GET /models*`, `POST /training/run`, `GET /training/status`, `POST /models/{v}/approve|reject` (este último solo tras aprobación humana en Telegram/Discord).
- Usa una API key propia (`N8N_API_KEY`) con scope reducido: no puede llamar a `/system/resume`.
- Nunca recibe ni envía órdenes; no conoce credenciales MT5.

## 6. Seguridad transversal

- Secretos solo por variables de entorno; `.env` está en `.gitignore`; `.env.example` sin valores.
- Logger con filtro de sanitización (passwords, tokens, login MT5 completo, API keys).
- Validación Pydantic de toda entrada externa (Crucix, API, n8n, futuros LLM).
- Ningún LLM ni n8n tiene acceso a `broker/` ni a `execution/`.
- Escaneo de secretos en CI (gitleaks) desde la Fase 1.

## 7. Despliegue (objetivo)

```text
Desarrollo (este PC, Windows 11)          VPS Windows (Fase 11)
├── Python 3.12 venv                       ├── MT5 terminal (demo)
├── MT5 terminal (demo, Fase 2+)           ├── trading-system (servicio, NSSM/Task Scheduler)
├── SQLite → PostgreSQL en Docker          ├── PostgreSQL
├── Crucix (npm run dev)                   ├── Crucix
├── Dashboard (vite dev)                   ├── n8n (opcional)
└── n8n en Docker (opcional)               └── backups + monitoreo + sincronización horaria
```

Nota: el paquete `MetaTrader5` solo funciona en Windows y necesita el terminal instalado. El proceso que habla con MT5 corre en el host Windows, no en un contenedor Linux.

## 8. Preguntas abiertas

| # | Pregunta | Cuándo se resuelve |
|---|----------|--------------------|
| Q1 | Formato real de `/api/data` de Crucix y qué campos existen | Fase 3 |
| Q2 | Broker de la cuenta demo (comisiones, spreads, divisa de la cuenta) | Parcial: MetaQuotes-Demo, USD. Sus spreads no son realistas; el broker regulado definitivo se elige antes de la Fase 11 |
| Q3 | Profundidad del histórico M15 disponible en el broker (¿≥ 3 años?) | **Resuelta:** ~4.1 años (desde 2022-09) |
| Q4 | Cómo clasificar risk-on/risk-off por par (USDJPY reacciona distinto) | Fase 4 |
| Q5 | Proveedor del VPS | Fase 11 |
| Q6 | ¿El broker demo conserva el `comment` de las órdenes? | Fase 2 |
