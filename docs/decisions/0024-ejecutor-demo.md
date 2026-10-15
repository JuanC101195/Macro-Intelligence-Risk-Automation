# ADR 0024 — Ejecutor demo (Fase 11, primera parte)

- Fecha: 2026-10-15
- Estado: aceptada

## Contexto

La Fase 7 (paper, ADR 0016) corre desde el 2026-10-15. Antes de cualquier dinero real hace falta comprobar el envío real de órdenes: llenado, deslizamiento, stops puestos, duplicados, desconexiones (`CLAUDE.md` §11, ADR 0017). Esta ADR fija cómo se construye el ejecutor; su conexión al ciclo de trading y la prueba en la cuenta demo van en una segunda parte.

## Decisión

- **Dónde vive:** `execution/demo_executor.py`, con la misma interfaz `Executor` que el paper (`submit`, `close`, `sync`, más `modify_stop`). Es el **único** archivo del paquete donde puede aparecer `order_send` (el test de arquitectura se relaja solo para él). `MetaTrader5` sigue importándose solo en `broker/mt5_client.py`: el ejecutor recibe el terminal de `Mt5Client.order_terminal()`, que se niega si la cuenta no es demo.
- **Candados, en cada envío (falla cerrado):** `TRADING_MODE=demo`, `ALLOW_DEMO_ORDERS=true`, `LIVE_TRADING_ENABLED=false` (la configuración ya los exige), la cuenta conectada es **demo** según el propio terminal, e `intent.mode == "demo"`. Si alguno falla, la orden se rechaza sin tocar el bróker.
- **Validación antes de enviar:** símbolo operable (y en corto si es venta), volumen dentro de mínimo/máximo y múltiplo del paso, stop obligatorio del lado correcto del precio actual y a la distancia mínima del bróker, TP del lado correcto.
- **Idempotencia:** cada orden lleva `magic = 260016` y `comment = intent_id` (16 caracteres, ADR de la Fase 5). Antes de enviar se busca ese `intent_id` en las posiciones abiertas y en los deals de los últimos 30 días; si ya existe, se devuelve `duplicate` con el ticket y **no** se envía.
- **Resultado:** `DONE`/`PLACED`/`DONE_PARTIAL` → `filled` (ticket, precio, deslizamiento en puntos). Recotización, precio cambiado, sin precios, mercado cerrado, stops o volumen inválidos, sin dinero → `rejected`, sin perseguir el precio. Sin respuesta, timeout, sin conexión o demasiadas peticiones → se **consulta el estado real**; si la orden aparece, `filled`; si no, **un solo reintento**; si sigue sin confirmarse, `unknown` (el ciclo debe abrir el circuit breaker).
- **Cierre:** orden opuesta con `position = ticket`; si la posición ya no existe (la cerró el stop o el TP), `duplicate`. **Mover stop:** `TRADE_ACTION_SLTP`.
- **Mensajes saneados:** solo código de retorno y comentario del bróker (recortado); nunca login ni contraseña.
- **Reconciliación** (`execution/reconciliation.py`): compara los tickets que el ciclo cree abiertos con las posiciones del bróker con nuestro `magic`. Tickets que ya no están → cerrados en el bróker (stop/TP o manual), se registran con su deal de salida. Posiciones nuestras que el ciclo no conoce → **circuit breaker**.
- Comando `demo check` (solo lectura): modo, candados, tipo de cuenta, especificación y modo de llenado del símbolo, spread actual. No envía nada.

## Consecuencias

- La segunda parte conecta el ejecutor al ciclo del paper (mismo `PaperTrader`, otro ejecutor), añade una orden de prueba mínima con confirmación y el registro de tareas para la demo.
- Juan pone en `.env` la contraseña de **operación** de la cuenta demo y activa `TRADING_MODE=demo` + `ALLOW_DEMO_ORDERS=true` solo cuando se vaya a probar.
