# ADR 0011 — Hipótesis: retroceso de Fibonacci con soportes y resistencias en oro (H1 + M5)

- Fecha: 2026-10-12
- Estado: aceptada (escrita **antes** de descargar los datos M5/H1 del oro, de escribir código o de ver cualquier resultado)
- Versión: `fibsr-xau-v001` (variante 1 de 20 del presupuesto de la ADR 0002)

## Contexto

Es la forma de operar de un socio del proyecto, descrita por él y traducida a reglas mecánicas. Opera XAUUSD en forma discrecional: analiza H1 (tendencia, Fibonacci, soportes y resistencias horizontales y diagonales) y busca la entrada en M5. Dos capturas suyas (un canal bajista con líneas diagonales y una venta en el 50 % de un tramo de ~415 USD, stop entre el 61.8 % y el 78.6 % y objetivo en el 0 %, beneficio/riesgo ≈ 2.25) sirvieron para fijar las reglas.

La traducción es nuestra y puede no coincidir con su criterio. Por eso hay un paso de **validación de la traducción** (abajo) antes de mirar resultados. Las iteraciones posteriores son variantes nuevas: cada una se registra como adenda **antes** de correrla y cuenta en el presupuesto de 20.

## Hipótesis

En XAUUSD, un retroceso al 50 %–61.8 % de un tramo H1 importante, que coincide con un soporte o una resistencia (horizontal o diagonal) y se confirma con una vela de giro en M5 a favor de la tendencia, tiene expectancy neta positiva y supera a entradas aleatorias con la misma gestión.

## Reglas (`fibsr-xau-v001`)

Sin mirar el futuro: un dato de H1 solo se usa cuando su vela H1 ya cerró antes del cierre de la vela M5 que decide, y un punto de giro solo existe desde la vela en que queda confirmado.

### 1. Tramos y tendencia en H1

- **Giros H1 (ZigZag):** un máximo queda confirmado cuando el precio cae desde él al menos **4 × ATR(14) H1**; un mínimo, cuando sube desde él lo mismo. El giro se fecha en su vela, pero existe desde la vela que lo confirma.
- **Tendencia H1:** bajista si los dos últimos máximos confirmados son decrecientes **y** los dos últimos mínimos también; alcista si ambos son crecientes. Si no, no se opera.
- **Confirmación M5 (último día):** mismo ZigZag en M5 con **4 × ATR(14) M5**, solo con giros de las últimas 288 velas (24 h). La tendencia M5 debe coincidir con la de H1 (dos máximos y dos mínimos en el mismo sentido). Si no hay giros suficientes en 24 h, no se opera.

### 2. Fibonacci

- **Tramo:** en tendencia bajista, del último máximo confirmado (100 %) al último mínimo confirmado posterior (0 %); en alcista, al revés.
- **Tamaño mínimo:** el tramo debe medir al menos **10 × ATR(14) H1** (en las capturas el tramo es un movimiento de varios días).
- **Franja de entrada:** entre el **50 %** y el **61.8 %** del retroceso.
- El tramo deja de servir si el precio supera el **78.6 %** (se invalida) o hace un nuevo extremo más allá del 0 % (se espera el tramo siguiente).

### 3. Soportes y resistencias (H1, última semana = 120 velas H1)

- **Puntos de toque:** fractales H1 de mecha (máximo o mínimo más extremo que las 3 velas de cada lado; existe 3 velas después).
- **Zona horizontal:** al menos **2** fractales del mismo tipo con precios a menos de **0.5 × ATR(14) H1** entre sí; la zona va del menor al mayor de ellos.
- **Línea diagonal:** recta por dos fractales del mismo tipo (dos máximos = resistencia, dos mínimos = soporte) separados ≥ 10 velas, con al menos un **tercer** fractal a menos de 0.5 × ATR de la recta, y sin ningún cierre H1 que la cruce entre el primer y el último toque. Su valor se proyecta a la vela actual. Todos los toques tienen que ser **anteriores** a la decisión.
- **Coincidencia obligatoria:** la franja 50 %–61.8 % debe solaparse con una zona horizontal o con el valor actual de una línea (± 0.5 × ATR H1). Para vender sirve una resistencia; para comprar, un soporte. Una línea rota pasa a contar del lado contrario solo si ya fue tocada después de romperse.

### 4. Gatillo en M5

Con el precio dentro de la franja (en una venta, el máximo de la vela M5 llega al 50 % y el cierre queda por debajo del 78.6 %; simétrico en compras), se entra cuando cierra en M5:

- **Envolvente** a favor de la tendencia: vela bajista cuyo cuerpo cubre el cuerpo de la vela alcista anterior (simétrico en compras); o
- **Rechazo:** mecha en contra ≥ **2 × cuerpo** y ≥ 50 % del rango de la vela, con el cierre en la mitad a favor.

La orden se ejecuta en la apertura de la vela M5 siguiente, como en todo el motor.

### 5. Salidas y gestión

- **Stop inicial:** en el nivel **78.6 %** del tramo.
- **Take-profit:** en el **0 %** del tramo.
- **Asegurar ganancia:** cuando el beneficio no realizado llega a **1 R** (lo arriesgado), el stop pasa a asegurar **0.5 R** (ejemplo del socio: con 10 USD ganados, asegura 5).
- **Stop que sigue al precio:** después de eso, el stop se mueve detrás de cada nuevo giro M5 confirmado a favor (en compras, debajo de cada mínimo más alto; en ventas, encima de cada máximo más bajo). Solo se mueve a favor, nunca en contra.
- Los cambios de stop se deciden al cierre de la vela M5 y valen desde la siguiente. Una operación a la vez.

### 6. Riesgo, costes y periodo

- Lotaje del **gestor de riesgo**: 0.25 % por operación, capital 17 500 equivalente a cuenta cent (ADR 0005). Nunca lote fijo.
- Como dato informativo (no cuenta para la Puerta A) se reporta también el resultado con **0.01 lote fijo**, que es como opera el socio: con el stop de las capturas (~93 USD), una pérdida con 0.01 lote es ~93 USD, más que la mitad del capital real previsto.
- Costes, slippage y financiación de XAUUSD según la ADR 0006. Sin filtro de horario ni de noticias en esta versión (el socio no lo definió; candidato a variante).
- Datos: XAUUSD M5 y H1 de MetaQuotes-Demo, toda la historia disponible. Hold-out: últimos 12 meses, bloqueado. Si la historia M5 no alcanza 3 años sin el hold-out, **A1 falla** y se reporta así; no se cambia el umbral.

### 7. Evaluación

- Puerta A completa (A1–A11), con A11 contra 200 versiones de entradas aleatorias (ADR 0010).
- **Vecinas para A9 (fijadas ahora):** ZigZag 3 × ATR y 5 × ATR; franja 38.2 %–61.8 %; stop en el 88.6 %; tolerancia de toques 0.25 × ATR y 0.75 × ATR.
- Se espera una muestra chica (un solo instrumento): A2 (≥ 300 operaciones) puede fallar por sí solo. Es información válida, no motivo para relajar reglas.

## Validación de la traducción (antes de ver resultados)

Antes de correr el backtest, se generan gráficos de las primeras 10 entradas detectadas en el periodo de investigación, **recortados en la vela de entrada** (sin mostrar qué pasó después). El socio dice si cada una es una entrada que él habría tomado. Si las reglas no se parecen a su criterio, se corrige la traducción con una adenda y se repite este paso; nada de eso usa resultados de rentabilidad.

## Adenda 2026-10-12 — periodo y memoria (antes de escribir código o ver resultados)

Descarga hecha: XAUUSD H1 (129 884 velas) y M5 (1 499 333 velas), ambos desde junio de 2004. Las velas M5 ocupan ~1.9 GB en memoria y cada proceso del modelo nulo (A11) necesita su copia; el PC tiene 13.8 GB. Por eso, y **solo** por eso:

1. El periodo de investigación empieza el **2016-01-01** en M5 (H1 desde 2015-07-01 para calentar ATR, ZigZag y fractales). Quedan ~9.8 años antes del hold-out, muy por encima de A1. El corte se fija sin haber corrido nada y no se mueve después.
2. El modelo nulo de esta hipótesis usa como máximo **4 procesos**.

## Consecuencias

- El motor necesita dos cosas nuevas: contexto H1 dentro de una estrategia que decide en M5 (sin mirar el futuro) y stops que se mueven durante la operación. Se implementan con tests de mecánica antes de la corrida.
- Hay que descargar XAUUSD H1 y M5 (MT5 en solo lectura).
- Que el socio opere en demo a mano en paralelo y anote cada operación es útil para comparar con las reglas; el **sistema** no opera en demo hasta pasar las Puertas A y B.
