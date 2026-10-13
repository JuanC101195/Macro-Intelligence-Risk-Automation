# ADR 0012 — Optimización walk-forward; hipótesis `fibsr-xau-v002`

- Fecha: 2026-10-12
- Estado: aceptada (escrita **antes** de implementar la optimización, de aplicar las correcciones o de correr cualquier backtest de la estrategia del socio)
- Hipótesis: `fibsr-xau-v002` (sustituye a `fibsr-xau-v001`, que nunca se corrió). Usa **12 de las 20** variantes del presupuesto de la ADR 0002.

## Contexto

La revisión del socio (ADR 0011, adendas) dejó dos cosas:

1. Siete de diez entradas coinciden con su criterio. Las tres que no, fallan por velas de gatillo débiles (dojis diminutos o de color contrario contados como rechazo, envolventes de velas sin cuerpo) y por entradas en las que el precio apenas rozó la franja.
2. Opera **mínimo 3 veces al día**, mientras que las reglas completas dan de 4 a 29 tramos al año según el tamaño del tramo. En la práctica no exige todas las condiciones a la vez, y no sabemos cuáles afloja.

En lugar de adivinar cuáles condiciones son obligatorias, se deja que lo decida una **optimización walk-forward**: cada 6 meses se elige la variante con la información anterior y se aplica a los 6 meses siguientes, que no ha visto. Elegir "la que más ganó" mirando todo el periodo está prohibido (ADR 0002, regla 5). Hacer la elección dentro del walk-forward la mantiene fuera de muestra.

## Decisión

### 1. Correcciones de traducción (valen para todas las variantes)

- **Vela de rechazo:** además de lo de la ADR 0011, debe **cerrar a favor** (bajista para vender, alcista para comprar) y su rango debe ser ≥ **1 × ATR(14) M5**.
- **Envolvente:** el cuerpo de la vela envuelta debe ser ≥ **0.3 × ATR(14) M5**.
- **Franja tocada de verdad:** desde que el tramo es conocido, al menos un **cierre M5 dentro de la franja** 50 %–61.8 % (puede ser la propia vela gatillo).
- "No entrar con mechas en contra" queda **fuera** de esta versión, porque no hay una definición acordada con el socio.

El resto de las reglas de la ADR 0011 se mantiene: stop en el 78.6 %, objetivo en el 0 %, +0.5 R asegurado al llegar a +1 R y stop que sigue los giros M5. También se mantienen el riesgo, los costes, los datos y el periodo, incluida la adenda de memoria.

### 2. Las 12 variantes (fijas)

| Dimensión | Valores |
|---|---|
| Escala del tramo H1 (ZigZag / tamaño mínimo, en ATR H1) | 1 / 2 · 2 / 4 · 4 / 10 |
| Confirmación de tendencia en M5 (24 h) | sí · no |
| Zona o línea obligatoria en la franja | sí · no |

3 × 2 × 2 = 12. La tendencia H1 sigue siendo la estricta: dos máximos y dos mínimos en el mismo sentido.

### 3. Método walk-forward

- Cada variante se corre una vez en todo el periodo de investigación con el motor propio (costes ×1). Sus operaciones solo se usan para **elegir**.
- **Ventanas de prueba:** 6 meses, desde el **2019-01-01** hasta el inicio del hold-out.
- **Entrenamiento:** los **36 meses** anteriores a cada ventana. Solo cuentan operaciones **cerradas** antes de que la ventana empiece.
- **Criterio de elección:** mayor expectancy en R (media de pnl / riesgo) entre las variantes con al menos **30 operaciones** en el entrenamiento. Si ninguna llega a 30 o la mejor tiene expectancy ≤ 0, **no se opera** en esa ventana. Los empates se resuelven por el orden de la tabla.
- **Resultado evaluado:** una sola corrida continua del motor con una estrategia que, en cada ventana, usa la variante elegida. El lotaje, los límites y las posiciones que cruzan de una ventana a otra se simulan de verdad, sin pegar resultados de corridas distintas.
- La Puerta A completa (A1–A11) se aplica a esa corrida:
  - **A6:** las ventanas de 6 meses fuera de muestra.
  - **A9 (vecinas):** el mismo procedimiento con entrenamiento de 24 meses, con entrenamiento de 48 meses y eligiendo por profit factor en lugar de expectancy.
  - **A11:** 200 versiones con entradas aleatorias calibradas con las entradas ejecutadas de esa corrida, con la misma gestión del stop.
- Hold-out: sigue bloqueado.
- Como información, y sin que cuente para la Puerta A, se reporta qué variante se eligió en cada ventana y el resultado con **0.01 lote fijo** (pnl × 0.01 / volumen).

### 4. Uso futuro

La optimización walk-forward queda disponible para otras hipótesis, siempre con su lista de variantes fijada en una ADR antes de correr y contando cada variante en el presupuesto de 20.

## Resultado (2026-10-12) — no pasa la Puerta A

Corrida walk-forward 2019-01 → inicio del hold-out (6.7 años fuera de muestra), costes ×1:

- **Fallan A2** (105 operaciones), **A3** (expectancy negativa), **A4/A5** (PF 0.73 / 0.70), **A6** (46 % de ventanas positivas), **A8**, **A9** (las tres formas de elegir dan expectancy negativa) y **A11**. Pasan A1 y A7 (drawdown 4.3 %).
- **A11:** el PF queda **por debajo de la mediana** de las 200 versiones con entradas aleatorias. Las entradas no aportan nada frente al azar con la misma gestión.
- **Elección:** cambia de variante casi cada semestre y en uno no opera. Las variantes con más puntaje de entrenamiento casi nunca llegaban a 30 operaciones. Es la señal típica de que no hay una variante con ventaja estable.
- **Gestión:** gana el 46 % de las veces, pero la ganancia media es menor que la pérdida media (≈ 0.8 R frente a ≈ 0.9 R). Solo 14 de 105 operaciones llegan al objetivo del 0 %; el resto sale por stop, la mayoría después de asegurar +0.5 R.
- **Con 0.01 lote fijo** (informativo): −117 USD en 6.7 años, con una racha negativa de 175 USD. Con 100 000 COP de capital (~25 USD), eso es la cuenta entera.

Revisión interna: las corridas por variante y la corrida combinada son coherentes (la elección solo usa operaciones cerradas antes de cada ventana, verificado por tests) y el nulo opera un número de veces comparable (81–127 frente a 105). No se ve ningún error del simulador.

Conforme a lo pre-registrado, **no se ajusta esta hipótesis sobre la historia**. Quedan 8 variantes del presupuesto, que solo se usan con una razón nueva y registrada antes de correr.

## Consecuencias

- El resultado medido incluye el costo de elegir: si la elección no aporta, se nota fuera de muestra.
- Las 12 corridas, la corrida combinada, sus vecinas y las 200 nulas tardan del orden de una hora con 4 procesos.
- Si `fibsr-xau-v002` no pasa la Puerta A, quedan 8 variantes del presupuesto. Cualquier cambio posterior se registra antes de correrlo, y la regla de las mechas solo entra con una definición acordada con el socio.
