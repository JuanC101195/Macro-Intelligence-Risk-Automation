# ADR 0021 — Hipótesis: ruptura del rango de apertura en índices de EE. UU. (`orb-us-v001`)

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** del código y de mirar los datos intradía de índices)

## Contexto

Las 17 hipótesis anteriores son casi todas análisis técnico de precio y solo una pasa la Puerta A, con pocas operaciones. Juan quiere operaciones casi a diario. Una fuente distinta de ventaja es el **momento del día**: la apertura de Nueva York concentra información (noticias de la noche, órdenes acumuladas) y la literatura reciente reporta que la dirección de los primeros minutos tiende a continuar durante la sesión (p. ej. Zarattini y Aziz, 2023, ruptura del rango de apertura de 5 minutos en el Nasdaq). Las reglas se toman de esa familia de estudios, **no** se ajustan a nuestros datos.

Riesgo conocido: los estudios usan ETF/futuros con costes bajos; aquí son CFD de MetaQuotes-Demo con spread más alto. Previo: moderado-bajo.

## Decisión

### Datos y universo

- **US500 y US30**, velas M1 de MetaQuotes-Demo (bid + spread por vela), desde que ambos tienen datos (~2016–2017) hasta el 2026-10-15. **USTEC queda fuera**: solo ~2 años de M1 (misma razón que en la ADR 0006). Veredicto de la **canasta completa** (todo o nada).
- Horario en hora de Nueva York (`America/New_York`, con cambio de horario): apertura 09:30, cierre 16:00. Días sin vela de las 09:30 se saltan.

### Reglas (versión `orb-us-vN`, N = minutos del rango)

1. **Rango de apertura:** las velas de 09:30 a 09:30 + N min. Apertura del rango = open de la primera vela; cierre = close de la última.
2. **Dirección:** cierre > apertura → **compra**; cierre < apertura → **venta**; igual → no se opera ese día.
3. **Entrada:** apertura de la vela siguiente al rango; compra al ask (bid + spread), venta al bid.
4. **Stop:** mínimo del rango (compra) o máximo del rango (venta). R = |entrada − stop|. Si R es menor que el spread de la vela de entrada, no se opera.
5. **Salida (lo primero):** stop; objetivo a **10 R**; o cierre a las **16:00** (close de la última vela antes de las 16:00). Stop y objetivo en la misma vela → cuenta el stop. Salidas de compras al bid, de ventas al ask.
6. **Costes:** spread de cada vela + deslizamiento de la mitad del spread de esa vela (mínimo 0.1 puntos de índice) por lado. Sin financiación (nunca se queda abierta de noche).
7. **Tamaño:** 0.25 % de riesgo por operación con tope de apalancamiento 4× el capital por posición (si el stop es muy corto, el tope manda). Una operación por índice y día.

### Versiones (2 pruebas)

- `orb-us-v5` (rango de 5 min) y `orb-us-v15` (rango de 15 min). Se evalúan por separado; no se elige entre ellas con los datos (cada una tiene su veredicto).

### Evaluación (Puerta A)

- Las reglas no se ajustan a los datos, así que **todo el periodo es fuera de muestra**. A1–A9 de la ADR 0002 con ventanas de 6 meses; costes ×1, ×1.5 y ×2.
- **A9 (vecinos):** para v5, rangos de 3 y 10 min; para v15, de 10 y 20 min; y objetivo 5 R y 15 R.
- **A10 no se evalúa** (hold-out ya usado; criterio de las ADR 0018–0020).
- **A11 (nulo de dirección), 200 versiones:** mismos días, misma hora de entrada, mismo stop (extremo opuesto del rango según la dirección sorteada) y mismas salidas; solo la dirección se sortea con la proporción de compras observada. Se corre solo si A1–A9 pasan.
- **Control informativo:** "comprar siempre" con las mismas reglas de stop y salida (los índices suben a largo plazo; la ventaja debe venir de la dirección, no de la deriva).
- Se reporta: operaciones por semana, % de semanas positivas, peor semana y mes, y vista en dólares con 10 USD por operación.

## Consecuencias

- Backtest vectorizado de laboratorio (`research/lab/orb_us.py`), con auditoría de 20 operaciones contra un bucle vela a vela. Si pasa, se porta a `src/` antes de paper.
- Datos M1 de índices locales (no se suben).
