# ADR 0013 — Evaluación del historial real del socio (oro discrecional)

- Fecha: 2026-10-15
- Estado: aceptada (escrita y commiteada **antes** de abrir el archivo del historial)

## Contexto

El socio de Juan opera oro de forma discrecional en una cuenta real. Las ADR 0011/0012 intentaron reproducir sus reglas (Fibonacci + soportes/resistencias) y fallaron: con las reglas completas salen 4–29 tramos al año, muy lejos de su frecuencia, y las entradas fueron peores que la mediana del azar. Se acordó dejar de adivinar sus reglas y medir directamente **sus operaciones reales**.

Llegó el informe de historial exportado de MT5 (`.xlsx`, unos 146 deals entre el 2026-04-19 y el 2026-10-15). **No se ha abierto.** Lo único que se conoce de antes es un día y medio del diario de la app (14–15 oct), que mostró: símbolo `XAUUSD.f` de un bróker distinto al nuestro, lote 0.03, modo hedging (a veces compra y venta abiertas a la vez), casi sin stop-loss (pone y quita el take-profit a mano) y posiciones que duran de minutos a más de un día. La hora del servidor es UTC+3. Ese conocimiento previo está registrado aquí para que no se cuele como ajuste posterior.

La pregunta es una sola: **¿sus entradas tienen ventaja frente al azar o el resultado se explica por el periodo y la gestión?** No se busca ninguna regla nueva en estos datos.

## Decisión

### 1. Datos y privacidad

- El archivo se lee desde `Descargas` y se copia solo a `research/` (local, ignorado por git). **Nunca** se sube al repo: número de cuenta, nombre, saldos y operaciones concretas quedan fuera. Al repo público solo llegan el código y conclusiones sin cifras de la cuenta.
- Unidad de análisis: la **posición cerrada** (apertura + cierre), no el deal. Cierres parciales se suman a su posición.
- Se excluyen depósitos, retiros, bonos y ajustes de saldo. Si faltan comisiones o swaps, se reporta.
- **Instrumento principal: oro** (`XAUUSD*`). Otros símbolos se describen aparte y no entran en el veredicto.
- Se usan todas las posiciones del periodo. No se recorta ningún mes ni se quita ninguna operación "rara"; si hay un error de datos evidente, se documenta en una adenda **antes** de calcular métricas.

### 2. Alineación con nuestros precios

Para las comparaciones contra el azar y para la peor pérdida abierta se usan nuestras velas M5 de `XAUUSD` (MetaQuotes-Demo), descargadas hasta al menos el 2026-10-16 antes del análisis.

- Hora: servidor del bróker = UTC+3 (comprobar cambio de horario en el periodo). Validación: el precio de entrada de cada operación debe caer dentro del rango alto–bajo de la vela M5 correspondiente, con tolerancia de 1.5 USD por diferencia de bróker. Si menos del 90 % coincide, se prueba con desfases de ±1 h; si ninguno llega al 90 %, se documenta y **no** se hace la comparación contra el azar (solo métricas descriptivas).
- El veredicto usa el resultado medido con nuestros precios, para comparar con la misma vara que los nulos. El resultado real del bróker se reporta al lado.

### 3. Métricas descriptivas (todas se reportan, ninguna sola decide)

- Número de posiciones, resultado neto (USD y en puntos × lote), profit factor, tasa de acierto, ganancia y pérdida media, expectancy por operación.
- Resultado por semana y por mes; semanas negativas; racha máxima de pérdidas; drawdown máximo sobre el saldo cerrado.
- Compras frente a ventas; duración de las posiciones; operaciones por día.
- **Peor pérdida abierta (MAE)** de cada posición, calculada con las M5: máxima, mediana y como % del saldo del momento si el saldo se puede reconstruir.
- **Riesgo de gestión:** % de posiciones sin stop-loss, posiciones contrarias abiertas a la vez, entradas añadidas a una posición que va perdiendo (promediar), y si el lote sube después de pérdidas (señal de martingala).
- Concentración: qué parte del neto aportan las 3 y las 10 mejores operaciones; resultado quitando las 3 mejores.

### 4. Pruebas contra el azar (10 000 simulaciones cada una, semilla fija)

Se miden en puntos × lote con nuestros precios M5 y un coste fijo por operación igual al spread mediano de nuestro `XAUUSD` en la hora de entrada.

- **N1 — dirección:** misma hora de entrada, misma duración y mismo lote de cada operación real; la dirección se sortea con la proporción de compras observada. Pregunta: ¿acierta la dirección más que el azar?
- **N2 — momento y dirección:** mismo día, mismo lote y misma duración; la hora de entrada se sortea entre las velas M5 de ese día dentro de su horario habitual (entre la primera y la última hora de entrada observadas en todo el historial), y la dirección como en N1. Pregunta: ¿elige mejor cuándo entrar?

Para cada nulo se reporta percentil y p-valor `(1 + #nulos ≥ observado) / (N + 1)` del resultado neto y del profit factor.

### 5. Veredicto (fijado antes de ver los datos)

- Si hay **menos de 30 posiciones de oro**: solo descripción, **sin veredicto**.
- **Sin evidencia de ventaja:** resultado neto ≤ 0, o el neto no supera el percentil 95 de N1 ni de N2.
- **Indicio:** neto > 0, profit factor > 1.2, al menos 50 posiciones y supera el percentil 95 de **uno** de los nulos.
- **Evidencia preliminar:** neto > 0, profit factor > 1.3, al menos 50 posiciones, supera el percentil 95 de **N1 y N2**, y sigue positivo quitando las 3 mejores operaciones.

Independiente del veredicto, se marca **riesgo de gestión alto** si más del 50 % de las posiciones no tienen stop-loss o si la peor pérdida abierta supera el 20 % del saldo.

### 6. Qué permite y qué no

- Ningún veredicto autoriza copiar sus operaciones con dinero real ni subir el lote. Seis meses de un solo trader son una muestra corta y con sesgo de supervivencia (nos llegó porque va bien o porque quiere mostrarlo).
- Con **indicio** o **evidencia preliminar**, el paso siguiente es medirlo **hacia adelante**: diario de operaciones en demo con stop-loss obligatorio, ≥ 100 operaciones, mismas métricas y nulos, con su propia ADR.
- Con **sin evidencia**, se le muestran los resultados al socio y se cierra esta línea; no se buscan "sus mejores días" ni filtros dentro de este historial.

## Adenda 1 — 2026-10-15 (bug antes de obtener resultados)

La primera ejecución falló sin producir métricas: algunas horas de apertura o cierre no tienen una vela M5 que empiece exactamente en ese bloque de 5 minutos (pausa diaria del oro, huecos de datos), y el índice devolvía "no encontrado". Corrección: cada hora se asigna a la **última vela que empieza en o antes** de ella. No cambia ningún criterio.

## Adenda 2 — 2026-10-15 (cambio de método DESPUÉS de ver un resultado)

**Resultado pre-registrado (se conserva tal cual):** con velas M5 el veredicto fue *sin evidencia de ventaja*. Pero al revisarlo, el mismo historial medido con nuestros precios dio una ganancia bruta de −119 USD, frente a +507 USD reales. La causa es la resolución: la mediana de duración es ~10 minutos y el precio de apertura de una vela M5 está lejos de sus llenados reales (sus cierres quedan en mediana 0.88 USD por encima de la apertura de la vela, porque sale por TP dentro de la vela). El método M5 no mide lo que se quiere medir.

Cambios, decididos antes de volver a correr:

1. **N1 (dirección) con los precios reales del bróker**, sin velas: cada simulación usa la apertura y el cierre reales de cada posición, con comisión y swap reales, y solo sortea la dirección. Lo observado es su resultado neto real. Es una medida exacta para la pregunta "¿acierta la dirección?".
2. **N2 (momento + dirección) y peor pérdida abierta con velas M1** (apertura de la vela del minuto). Lo observado para N2 se mide con la misma vara (M1).
3. **Regla conservadora por cambiar después de mirar:** si con este método el veredicto sale favorable, se **baja un nivel** (evidencia preliminar → indicio; indicio → sin evidencia de ventaja con "señal débil" anotada). El resultado M5 original se reporta al lado.

## Cierre — 2026-10-15

Veredicto final: **sin evidencia de ventaja (señal débil)**, con riesgo de gestión alto. Juan decide **cerrar esta línea**: no se pedirán más datos al socio ni se hará la medición hacia adelante. El proyecto sigue solo con la estrategia propia (`trendbo-xau-h4-channel`, ADR 0014) y sus fases 7 y 11.

## Consecuencias

- El análisis es un script de laboratorio (`research/lab/partner_history.py`), sin tocar `src/`. Sus resultados quedan en `research/reports/` (local).
- Las 10 000 simulaciones por nulo no cuentan como variantes del presupuesto de 20 (no son hipótesis nuevas).
- El diario de la app (con números de cuenta e IPs) no se guarda en el repo.
