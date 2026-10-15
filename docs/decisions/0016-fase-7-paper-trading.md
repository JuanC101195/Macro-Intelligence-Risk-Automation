# ADR 0016 — Fase 7: paper trading de `trendbo-xau-h4-channel`

- Fecha: 2026-10-14
- Estado: aceptada (escrita **antes** del código de la Fase 7)
- Relacionadas: ADR 0002 (Puerta B), ADR 0005 (capital), ADR 0014 (estrategia), ADR 0015 (lotaje)

## Contexto

`trendbo-xau-h4-channel` es la única regla que cumple la Puerta A, con evidencia débil (ADR 0014). El backtest supone costes fijos (spread 30 puntos y slippage 5 puntos en XAUUSD) y llenado en la apertura de la vela siguiente. La Fase 7 debe medir si eso se cumple con precios reales y si la tubería funciona sin errores, **sin enviar ninguna orden** (la conexión MT5 sigue siendo de solo lectura, con contraseña de inversor).

Con unas 23 señales al año, 8 semanas de paper dan del orden de **3 a 5 operaciones**. Eso **no dice nada sobre la ventaja** de la estrategia. Lo que sí mide el paper es la tubería, los costes reales y si el sistema reproduce el backtest.

## Decisión

### Qué corre

- La estrategia `trendbo-xau-h4-channel` **congelada**: EMA 50/200, ruptura de 20 velas, stop 2 × ATR(14) y salida por el canal de 10 velas. Mismos parámetros que la ADR 0014. No se cambia nada durante el paper (ADR 0002, regla 5).
- Gestor de riesgo `DefaultRiskEngine` en modo `paper`, con los mismos límites del backtest de la ADR 0014. Los límites de spread y slippage siguen **desactivados** para replicar el backtest, pero ambos se **registran**.
- Capital simulado: **17 500** en unidades de cuenta cent (= 175 USD reales, ADR 0005). Lote **proporcional** (ADR 0015): 0.5 % de riesgo, redondeado hacia abajo, mínimo 0.01 (si no alcanza, se rechaza y se registra) y **tope 0.05**.

### Cómo corre

- Comando idempotente `trading-system paper tick`, ejecutado cada 5 minutos por una tarea programada de Windows en el PC de Juan. Más adelante se migra a un VPS Windows.
- En cada ejecución:
  1. Lee de MT5 las últimas 3 000 velas H4 cerradas (para que las EMA converjan igual que en el backtest) y el tick actual.
  2. **Verificación de frescura:** si la última vela cerrada es más vieja de lo que indica el tick (otra vela H4 ya debió cerrar), los datos están desincronizados. No decide nada, registra `stale_data` y sale. Ya pasó el 2026-10-14: el terminal recién abierto devolvió velas de 2 días antes.
  3. Procesa **solo las velas cerradas nuevas** desde la última procesada, en orden, con la misma secuencia del motor: salidas por stop/TP con el alto y el bajo de la vela, salida por canal al cierre y decisión al cierre.
  4. La primera ejecución no reconstruye el pasado: arranca desde la última vela cerrada.
- **Llenados:**
  - Entrada y salida por canal **a tiempo**, es decir, procesadas dentro de los 15 minutos posteriores al cierre de la vela: al tick real (ask para comprar, bid para vender). Se guarda el spread observado.
  - Si el PC estaba apagado y la vela se procesa tarde: una entrada nueva se registra como **señal perdida** y no se opera. Una salida por canal se ejecuta al cierre de la vela con el spread del modelo de costes, como en el backtest, y queda marcada como tardía.
  - Stop y TP dentro de una vela: con las reglas de `backtest/fills.py` (gap, stop primero, TP al precio límite) y el spread del modelo de costes, porque no se sabe el spread real en ese instante.
- **Swap:** no se simula en esta versión. Se documenta como limitación y se anota en el reporte. Las posiciones H4 duran días, así que el efecto es pequeño pero no nulo.

### Persistencia

- SQLite (`data/paper/paper.db`, fuera de git) con la librería estándar de Python y una tabla de versión de esquema.
- **Desviación de CLAUDE.md §4** (SQLAlchemy + Alembic + PostgreSQL): se pospone a la Fase 9 (API). Hoy habría que añadir dependencias y migraciones para una sola tabla de estado, y el `uv.lock` con hashes bloquea cambios pequeños. Se migra cuando exista la API.
- Se guarda: estado (última vela procesada, saldo, breaker), posición abierta, operaciones cerradas, cada señal con su decisión (operada, rechazada con motivo, perdida, en contra de la tendencia) y cada ejecución (ok, `stale_data`, error).

### Ejecutor y reconciliación

- `PaperExecutor` implementa la interfaz `Executor` de `execution/order_intent.py` (`submit`, `close`, `sync`), igual que lo hará el ejecutor demo.
- La clave de idempotencia es el `intent_id` determinista. Una vela ya procesada, o un mismo `intent_id`, nunca abre dos veces (B2: reinicios sin duplicados).
- **Reconciliación contra el backtest (B3):** `trading-system paper report` vuelve a correr el motor de backtest sobre las mismas velas del periodo de paper y compara, operación por operación, señales, entradas y salidas. Toda diferencia que no se explique por el llenado real (precio y spread del tick) es un bug.

### Reporte

`paper report` muestra:
- señales, operaciones y rechazos con su motivo;
- señales perdidas por PC apagado y ejecuciones con datos desincronizados;
- spread observado al llenar frente a los 30 puntos del modelo;
- resultado en cents y en USD reales;
- paridad con el backtest.

## Criterios (Puerta B de la ADR 0002, con lo que se puede medir aquí)

- **B1:** ≥ 8 semanas en paper.
- **B2:** cero errores no controlados; reinicios sin duplicados. Las ejecuciones con `stale_data` no cuentan como error, porque están controladas.
- **B3:** la paridad con el backtest no tiene diferencias inexplicadas. La expectancy no se puede evaluar con 3 a 5 operaciones, y se dice así en el reporte.
- **B4:** la mediana del spread observado al llenar no supera los 30 puntos. Si lo supera, se recalcula la Puerta A con el spread real **antes** de pasar a demo.
- **Paradas:** las de la ADR 0002 (drawdown > 1.5 × el máximo fuera de muestra, etc.).

## Consecuencias

- Si el PC está apagado se pierden señales. Se miden, y esa medición decide si vale la pena el VPS.
- Ninguna orden llega al bróker. El ejecutor demo es la Fase 11.
- El paper no puede confirmar que la estrategia funcione, solo que el sistema hace lo que el backtest dice.

## Adenda 1 (2026-10-14): velas que cierran con el mercado cerrado

La medición del spread histórico (ADR 0017) mostró que al cierre de las 21:00 UTC no hay ticks, por la pausa diaria del oro, y que lo mismo pasa con el cierre del viernes. Con la regla original, el paper decidía y llenaba en ese cierre con el último tick **anterior** a la pausa, un precio que no se puede operar. El backtest, en cambio, llena en la apertura de la vela siguiente, es decir, en la reapertura.

Corrección: la última vela cerrada se procesa solo cuando ya existe una vela M1 abierta **después** de su cierre, o sea, cuando el mercado reabrió. "A tiempo" pasa a medirse desde esa reapertura: dentro de 15 minutos se llena al tick real; si no, la entrada queda como perdida. Mientras el mercado siga cerrado, la vela espera a la siguiente corrida (estado `waiting_market`).
