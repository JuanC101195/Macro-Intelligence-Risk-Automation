# ADR 0005 — Capital real del proyecto y metas realistas

- Fecha: 2026-10-12
- Estado: aceptada

## Contexto

El capital con el que se piensa operar en el futuro es **entre 100 000 y 700 000 COP** (≈ 25 a 175 USD con el dólar en torno a 4 000 COP). Hasta ahora los backtests simulaban 10 000 o 100 000 USD, que no es la realidad del proyecto.

## Consecuencias del capital pequeño

- En una cuenta estándar el lote mínimo es 0.01. En EURUSD eso es ≈ 0.10 USD por pip: con un stop de 20 pips se arriesgan ≈ 2 USD, es decir **≈ 8 % de 25 USD**, 32 veces el límite de 0.25 % de `risk-policy.md`. El gestor de riesgo rechazaría todas las operaciones (correcto).
- Con ese capital solo es viable una **cuenta cent** (o micro), donde 0.01 lotes valen 100 veces menos. Muchos brókers con cuentas cent no están regulados: la elección del bróker se hace antes de la Fase 11, verificando su regulación.
- **Simulación equivalente:** una cuenta cent de 175 USD tiene la misma relación "lote mínimo / capital" que una cuenta estándar de **17 500 USD**. Los backtests de hipótesis nuevas usan 17 500 unidades de capital inicial y especificaciones de lote estándar; los resultados se leen en **porcentaje**.
- El capital real se considera **dinero perdible en su totalidad**. Su propósito en la Fase 11/12 es validar la ejecución real, no generar ingresos.

## Metas realistas

- Un objetivo como "100 USD por semana" con 175 USD equivale a ~57 % semanal (~3 000 % anual): no es alcanzable sin un riesgo que lleva a la ruina. Ningún parámetro del sistema se ajustará para perseguirlo.
- Referencia de éxito: una estrategia que pase la Puerta A con rentabilidad anual del orden de 10–25 % y drawdown ≤ 10 %. Con 175 USD eso son decenas de dólares al año; el valor está en tener una ventaja **validada**, escalable con más capital propio o con una cuenta de fondeo (prop firm) en el futuro.
- Nada de martingala, grid o aumento del lote tras pérdidas o ganancias: el tamaño lo decide solo el gestor de riesgo.
