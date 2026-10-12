# ADR 0009 — vectorbt como laboratorio de auditoría y pruebas contra el azar

- Fecha: 2026-10-12
- Estado: aceptada (escrita **antes** de instalar vectorbt o ejecutar cualquier prueba)

## Contexto

Diez hipótesis no pasaron la Puerta A. La última (`regime-h4-v001`, ADR 0008) mejora a su control, pero no sabemos si esa mejora es mayor que la que daría **cualquier** filtro que quite la misma proporción de señales. Además, el motor de backtest propio solo se ha verificado con tests de mecánica y revisiones manuales; los 4 bugs encontrados hasta ahora aparecieron revisando resultados raros.

[vectorbt](https://github.com/polakowo/vectorbt) (1.1.2) es un motor de backtest vectorizado (numpy/numba) con simulación por señales, señales aleatorias y barridos de parámetros. Licencia Apache 2.0 + Commons Clause: libre para investigar, **prohibido vender** un producto o servicio que sea principalmente vectorbt.

## Decisión

### Reglas de uso

1. vectorbt es **solo laboratorio**: extra opcional `research` en `pyproject.toml` y un entorno aparte (`.venv-research`), porque exige pandas 3 / numpy ≥ 2.4.6 y no debe tocar el `.venv` donde vive MetaTrader5. CI no lo instala. Nunca se importa desde `strategy/`, `risk/`, `execution/` ni `broker/` (test de arquitectura).
2. **No se usa para optimizar ni elegir parámetros.** Todo barrido que se ejecute cuenta como pruebas en el balance de la ADR 0002.
3. El veredicto de una hipótesis **sigue siendo** el motor propio + la Puerta A. vectorbt no modela el gestor de riesgo, el lotaje cent, los límites de cartera, el swap ni la cancelación por huecos.

### Prueba 1 — auditoría cruzada del motor

Señales de `breakout-h4-v001` (ADR 0008), **un instrumento a la vez** (sin límites de cartera), en el periodo de investigación. Se compara cada operación del motor propio con la de `Portfolio.from_signals` de vectorbt con las mismas entradas/salidas, ejecución en la apertura siguiente, el mismo stop por operación, sin take-profit, y costes equivalentes (spread y slippage del modelo de costes).

Criterio: mismas fechas de entrada y salida y mismo motivo (stop / señal) en ≥ 99 % de las operaciones, y precios de entrada y salida dentro de spread + slippage. Toda diferencia por encima de eso se investiga hasta saber de qué lado está el error antes de cualquier otra corrida. En el mismo paso, el GMM en Python puro (ADR 0008) se compara con `GaussianMixture` de scikit-learn con la misma inicialización: medias y pesos iguales a 1e-4.

### Prueba 2 — filtro de régimen contra filtros aleatorios (pre-registrada)

- **Nula:** un filtro que, por instrumento y vela, marca "tendencia" al azar con la misma probabilidad que la proporción de velas de tendencia que el GMM asignó a ese instrumento, solo en las velas en que el GMM tenía modelo.
- **200** filtros aleatorios con semillas 0–199, cada uno corrido con el **motor propio** y la configuración base de `regime-h4-v001` (costes ×1, sin vecinas).
- **Criterio:** el filtro GMM "aporta información" si su profit factor supera el **percentil 95** de los 200 filtros aleatorios. Se reporta también su percentil en expectancy y drawdown.
- No cambia el resultado de la ADR 0008 (no pasó la Puerta A). Solo decide si los regímenes merecen otra hipótesis: si no supera el percentil 95, se abandona la línea de regímenes.

### Fuera de alcance de esta ADR

Montecarlo de drawdown, Deflated Sharpe Ratio y mapas de estabilidad: se harán con su propia ADR si las pruebas 1 y 2 salen bien.

## Consecuencias

- Una dependencia pesada (numba, pandas 3, scikit-learn) entra solo en el extra `research` y en `uv.lock`; el núcleo y CI no cambian.
- Las pruebas contra el azar pasan a ser parte del método: una mejora que no supera a filtros o entradas aleatorias no se considera evidencia.
