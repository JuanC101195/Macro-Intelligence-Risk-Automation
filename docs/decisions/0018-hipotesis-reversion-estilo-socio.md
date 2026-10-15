# ADR 0018 — Hipótesis: reversión de corto plazo en oro, estilo del socio (`fade-xau-v001`)

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** de escribir el backtest y de descargar la historia M1)

## Contexto

La ADR 0013 midió las 70 operaciones reales de oro del socio (3 semanas): resultado positivo, entradas mejores que el azar en momento (N2, p≈0.03) pero no en dirección (N1, p≈0.07), veredicto "sin evidencia (señal débil)" y riesgo de gestión alto (73 % sin stop). Juan cerró la línea de pedirle datos y pidió **simular su comportamiento** para tener muchas operaciones sin depender de él.

Rasgos medidos en sus operaciones (análisis descriptivo, 2026-10-15), con *D* = mediana del movimiento absoluto del oro en 60 minutos dentro de su horario (6.93 USD en su periodo):

| Rasgo | Socio | Azar (mismos días) |
|---|---|---|
| Entra contra el movimiento de los 60 min previos | 80 % | 51 % |
| Movimiento previo de 60 min (en contra) | −0.69 *D* | ≈ 0 |
| Posición en el rango de las 4 h previas (0 = mínimo) | 0.34 | 0.51 |
| Ganancia típica / pérdida típica (precio) | +0.43 *D* / −0.62 *D* | — |
| Stop cuando lo pone | 0.73 *D* | — |
| Duración (mediana / percentil 75) | 10 / 103 min | — |
| Horario (UTC) | 04–06 y 12–16 | — |

Es una hipótesis de **reversión a la media de corto plazo** ("comprar la caída, vender el rebote"), distinta a todo lo probado (tendencia, ruptura, carry, pares, Fibonacci). Riesgo conocido: se diseñó mirando 3 semanas de un periodo (el oro bajó de ~4 300 a ~4 090), así que ese periodo queda **fuera** de toda prueba.

## Decisión

### Reglas (versión base)

- **Datos:** XAUUSD M1 (MetaQuotes-Demo, precio bid y spread por vela), desde 2010-01-01 hasta 2026-09-23 (el día antes del periodo del socio). Lo posterior queda fuera.
- ***D*:** mediana de |cierre − cierre de 60 min antes| en los minutos de sesión de los **20 días hábiles previos** (solo pasado; se recalcula una vez por día).
- **Sesión de entrada:** minutos con hora UTC en {04, 05, 06, 12, 13, 14, 15, 16}.
- **Señal al cierre de la vela M1 *t*:**
  - `ret60` = cierre(*t*) − cierre(*t* − 60); `pos4h` = (cierre(*t*) − mínimo) / (máximo − mínimo) de las 240 velas previas a *t* (sin incluir *t*).
  - **Compra** si `ret60 ≤ −k·D` y `pos4h ≤ 0.35`. **Venta** si `ret60 ≥ +k·D` y `pos4h ≥ 0.65`.
- **Ejecución:** apertura de la vela *t* + 1; compra al ask (bid + spread de esa vela), venta al bid. Deslizamiento extra 0.05 USD por lado. Comisión 10 USD por lote ida y vuelta (la del socio).
- **Salida (lo que ocurra primero):** take-profit a **0.45·D** del precio de entrada; stop-loss a **s·D**; cierre por tiempo a los **120 min**. Si stop y TP caen en la misma vela, cuenta el **stop** (conservador). Las salidas de compras se valoran al bid y las de ventas al ask.
- **Una posición a la vez** (sin promediar). Sin nuevas entradas en los 5 minutos siguientes a una salida.
- **Tamaño:** 0.25 % de riesgo por operación según la distancia del stop (para A7), sobre 10 000 USD.

### Variantes (8, presupuesto ≤ 20)

| Parámetro | Valores |
|---|---|
| *k* (caída previa) | 0.7, 1.0 |
| *s* (stop) | 0.75, 1.5 |
| Dirección | ambas, solo compras |

El TP (0.45·D), la sesión, `pos4h` y el tope de 120 min **no** se varían.

### Evaluación (Puerta A, ADR 0002 + A11 de la ADR 0010)

- **Walk-forward anual:** se entrena con 3 años, se elige la variante con mayor profit factor (mínimo 100 operaciones en el entrenamiento) y se aplica al año siguiente. Ventanas de prueba 2013 → 2026-09-23. El OOS es la unión de los años de prueba.
- Criterios A1–A9 y A11 como en las ADR 0002 y 0010. **A10 no se evalúa** (hold-out ya usado, `research/reports/holdout_used.json`); la Puerta A puede pasarse sin A10 solo con el aviso explícito de que no hay hold-out.
- **A11 (nulo):** 200 versiones con entradas aleatorias en los mismos minutos de sesión, con la misma probabilidad de entrada por día que las operaciones ejecutadas, la misma proporción de compras y las mismas salidas (TP, stop y tiempo en unidades de *D*).
- **A9:** vecinos en la rejilla (*k* y *s* contiguos) con expectancy > 0.

### Variante informativa "como opera el socio" (no se evalúa ni se opera)

Mismas entradas, TP 0.45·D, **sin stop**, cierre por tiempo a 24 h, lote fijo 0.03 sobre 8 400 USD. Solo para mostrar qué le habría pasado en 16 años a su forma de gestionar: peor pérdida abierta, peor día, peor mes y si la cuenta habría sobrevivido.

### Implementación

- Backtest vectorizado de laboratorio en `research/lab/fade_xau.py` (numpy), porque 16 años de M1 (~6 millones de velas) × 200 nulos no caben en el motor propio en tiempo razonable.
- **Auditoría obligatoria antes de creer el resultado:** reproducir a mano 20 operaciones al azar (entrada, salida y resultado contra las velas) y comparar un mes completo con una implementación simple en bucle; cualquier diferencia se investiga antes de reportar.
- Si alguna variante pasa la Puerta A, se porta a `src/` y se re-ejecuta con el motor propio antes de pasar a paper (Fase 7).

## Consecuencias

- Hay que descargar M1 de 2010 a 2026 (~6 M velas; local, no se sube).
- Si no pasa, la idea del estilo del socio queda descartada también como estrategia mecánica; no se afina (regla de pivotar, no afinar).
- Ningún resultado de esta ADR autoriza operar como el socio sin stop.
