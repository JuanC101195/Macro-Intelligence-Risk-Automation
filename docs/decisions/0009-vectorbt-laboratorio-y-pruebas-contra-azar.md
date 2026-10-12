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

## Adenda 2026-10-12 — prueba 1 (antes de ejecutar la comparación del motor)

- La comparación con vectorbt se hace con **costes en cero en ambos motores**: el motor propio modela bid/ask (un SHORT sale al ask y su stop se activa con el ask), y vectorbt usa una sola serie OHLC, así que con costes las diferencias serían de modelado y no de mecánica. Los costes ya están cubiertos por los tests con precios calculados a mano (`tests/backtest/test_engine.py`).
- Se aplica en las señales de vectorbt la misma regla del motor de cancelar una entrada si la vela siguiente no es contigua (huecos de fin de semana o de sesión), y el mismo stop y take-profit en precio (convertidos a fracción del precio de entrada).
- Se excluye la última operación de cada instrumento si queda abierta al final del periodo (el motor propio la cierra por `end_of_data`).
- Resultado de la parte del GMM (ya ejecutada): coincide con scikit-learn hasta 1e-13 en medias y pesos, con el mismo número de iteraciones.

## Resultado de la prueba 1 (2026-10-12) — pasa

Motor propio contra vectorbt, `breakout-h4-v001`, 11 instrumentos uno a uno, costes en cero (`research/lab/audit_engine.py`): **3 139 operaciones, 95.9 % idénticas** (mismas velas de entrada y salida, mismos precios) y el **100 %** explicado con cuatro diferencias de convención, todas a favor de la prudencia del motor propio:

1. El motor propio revisa el stop en la misma vela del fill (entra a la apertura; si después la vela toca el stop, sale). vectorbt no revisa stops en la vela de entrada (113 operaciones).
2. Tocar exactamente el stop lo ejecuta en el motor propio (1).
3. Un take-profit atravesado por un hueco se llena al precio límite en el motor propio y a la apertura en vectorbt (1).
4. vectorbt admite una orden y un precio por vela: no puede expresar "entrar a la apertura y salir al cierre" ni "ignorar una entrada y salir al cierre" en la misma vela (1), y las diferencias anteriores dejan posiciones abiertas más tiempo en vectorbt, lo que desplaza las entradas siguientes (cascada, 12).

No se encontró ningún bug en el motor propio. Al montar la comparación salieron dos errores **del script de auditoría** (redondeo del stop y conflictos de señales en vectorbt), corregidos antes del resultado final.

## Resultado de la prueba 2 (2026-10-12) — el filtro GMM no supera al azar

200 filtros aleatorios con la misma proporción de velas "tendencia" por instrumento, motor propio, configuración base (`research/lab/null_regime.py`; la corrida del filtro GMM reproduce exactamente el resultado de la ADR 0008). El profit factor del filtro GMM queda en el **percentil 77** de los aleatorios (p ≈ 0.23), **por debajo del percentil 95** exigido. Un filtro aleatorio típico ya mejora al control sin filtro casi tanto como el GMM: la mejora de la ADR 0008 frente a su control **no es evidencia de que los regímenes aporten información**. El drawdown del GMM es menor que el de la mayoría de los aleatorios, pero eso no era el criterio y no se usa a posteriori.

Conforme a lo pre-registrado: **se abandona la línea de regímenes**.
