# ADR 0008 — Hipótesis H-REGIME-1: ruptura H4 filtrada por regímenes (mezcla gaussiana)

- Fecha: 2026-10-12
- Estado: aceptada (pre-registro: escrita **antes** de escribir código o ejecutar cualquier prueba)

## Contexto

Ocho hipótesis no pasaron la Puerta A. La ruptura multi-activo en D1 (ADR 0006) fue de las menos malas, pero con pocas operaciones: un filtro sobre ella **no puede** pasar la A2 (≥ 300 operaciones), porque un filtro solo quita operaciones. Por eso esta ADR mueve la misma lógica de ruptura a **H4** (≈ 6 velas por día) y le añade un filtro de régimen.

Idea: el seguimiento de tendencia gana en mercados que se mueven de forma direccional y pierde en rangos, donde las rupturas son falsas. Una **mezcla gaussiana** (GMM, clases 08-09 del curso de ML) sobre dos medidas del comportamiento reciente del precio clasifica cada vela en un régimen. Solo se permiten entradas nuevas en el régimen "tendencia".

Prior honesto: **bajo**. Son dos cambios a la vez (timeframe y filtro): la ruptura de canal en H4 tiene menos respaldo que en D1 y los costes pesan más en movimientos más cortos. Los filtros de régimen suelen mejorar el drawdown más que la expectancy.

## Dos hipótesis pre-registradas en esta ADR

| Versión | Qué es | Para qué |
|---------|--------|----------|
| `breakout-h4-v001` | La ruptura de la ADR 0006 tal cual, en H4, **sin filtro** | Control: separa el efecto del timeframe del efecto del filtro |
| `regime-h4-v001` | La misma, con entradas solo en régimen "tendencia" | La hipótesis principal |

Las dos se evalúan contra la Puerta A y cuentan como dos hipótesis en el balance (pruebas múltiples: un aprobado de una sola sería más débil y se dirá así).

## Universo y datos

Los 11 instrumentos de la ADR 0006 tras su adenda (XAUUSD, XAGUSD, US500, US30, EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF), velas **H4** de MetaQuotes-Demo, descargadas con hash. El periodo de investigación empieza cuando todos tienen datos **más** la ventana de entrenamiento del GMM (para que el control y la principal operen exactamente en el mismo periodo). Hold-out de 12 meses no se usa.

Profundidad H4 encontrada al descargar (antes de cualquier prueba): FX desde 2004-01, XAUUSD desde 2004-06, XAGUSD desde 2008-11, **US500 y US30 desde 2012-08**. Por tanto los datos comunes empiezan en 2012-08 y **se opera desde 2014-08** (2 años de entrenamiento) hasta el inicio del hold-out (≈ 2025-10): unos 11 años. Cada instrumento entrena su GMM con su propia historia previa (el FX puede usar velas anteriores a 2012). En la vecina de 3 años de entrenamiento, los índices no tienen régimen (no operan) hasta 2015-08; el periodo no cambia.

## Reglas de la ruptura (ambas versiones)

Idénticas a `breakout-v001` (ADR 0006), contadas en velas H4: entrada al cierre que supera el máximo/mínimo de las **55** velas anteriores, salida por el canal de **20**, stop **2 × ATR(20)**, take-profit no vinculante 20 × ATR con piso del 10 % para SHORT, máximo **3 posiciones**, una por instrumento, riesgo **0.25 %**, capital **17 500** (ADR 0005), spreads/slippage/financiación de la ADR 0006, límite de spread del gestor desactivado, exposición por divisa a 1×.

## Filtro de régimen (`regime-h4-v001`)

Por instrumento, al cierre de cada vela H4 y **solo con datos pasados**:

1. **Características** (ventana de **30** velas ≈ 1 semana de mercado):
   - `vol` = logaritmo de la desviación estándar de los retornos logarítmicos de las 30 velas;
   - `er` = *efficiency ratio* de Kaufman: |ln C<sub>t</sub> − ln C<sub>t−30</sub>| / Σ |Δ ln C| de esas 30 velas (0 = ruido, 1 = movimiento en línea recta).
2. **Modelo:** mezcla gaussiana de **K = 3** componentes con covarianza completa 2×2, ajustada por EM sobre las características **estandarizadas** (media y desviación de la ventana de entrenamiento) de las últimas **2 años** de velas (≈ 3 100). Inicialización determinista: las muestras se ordenan por `er` y se parten en K grupos iguales; medias y covarianzas iniciales de cada grupo. Máximo 200 iteraciones, parada cuando la log-verosimilitud media mejora menos de 1e-6; se suma 1e-6 a la diagonal de cada covarianza.
3. **Reajuste:** cada **6 meses** (primera vela H4 de enero y de julio), con la ventana que termina en la vela anterior. Entre reajustes el modelo no cambia.
4. **Régimen "tendencia":** la componente con mayor `er` medio (en unidades originales).
5. **Filtro:** una entrada nueva solo se permite si la componente más probable (posterior máxima) de la vela de la señal es la de tendencia. Las salidas y los stops no se filtran.

Se implementa en Python puro (el proyecto no depende de numpy ni de scikit-learn).

## Variantes vecinas (A9, fijadas aquí)

- `regime-h4-v001`: K = 2 / K = 4; ventana de características 20 / 50; ventana de entrenamiento 1 / 3 años.
- `breakout-h4-v001` (control): las de la ADR 0006 — entrada 40 / 70, salida 15 / 30, stop 1.5 / 2.5 × ATR.

## Criterio de éxito

Puerta A de la ADR 0002 sin cambios, para cada versión. Lectura adicional (no decide nada): si la principal mejora claramente al control en profit factor y drawdown, el filtro aporta aunque no alcance la puerta.

Si ninguna pasa: se descarta la familia de ruptura (D1 y H4) y se recomienda pasar a la Fase 7 antes de cualquier hipótesis nueva.
