# Política de modelos

> El ML es opcional y llega tarde (Fase 8). Antes tienen que existir baseline, backtest reproducible y paper trading.

## 1. Rol del modelo

- Es un **filtro** sobre la señal baseline: puede bajar la confianza o pasar a `HOLD`.
- No puede generar señales desde `HOLD`, mover SL/TP, calcular volumen ni saltarse el riesgo.
- Sin modelo activo, el sistema funciona solo con la baseline.

## 2. Datos y etiquetas

- Label principal: `1` si se alcanza el TP antes que el SL, `0` si se alcanza primero el SL, usando el **mismo** SL/TP (ATR) que la baseline y costes incluidos.
- Si en una misma vela se tocan ambos ⇒ se toma SL (conservador).
- Horizonte máximo N velas; si no se toca ninguno ⇒ se excluye o se etiqueta por P&L neto (documentado en `label_spec`).
- Features solo con información disponible **al cierre** de la vela `t`. Features macro alineadas con la marca de tiempo en que se conocían (sin look-ahead).

## 3. Validación

- Splits cronológicos: train → validation → test, con un **embargo** entre ellos (≥ horizonte de la etiqueta).
- Walk-forward con ventanas rodantes; se reporta cada ventana, no solo el agregado.
- Comparación obligatoria contra: baseline sin filtro, modelo ingenuo (siempre 1 / tasa base), modelo anterior y buy-and-hold cuando aplique.
- Métricas: expectancy, profit factor, max drawdown, Sharpe, Sortino, win rate, nº de operaciones, estabilidad por ventana, sensibilidad a costes (×1.5 y ×2), rendimiento por régimen macro. Accuracy/AUC son secundarias.

## 4. Ciclo de vida

```text
candidate ──(validación automática OK)──► validated ──(aprobación humana)──► approved ──(activación manual)──► active
    │                                          │                                                              │
    └──────────► rejected ◄────────────────────┘                                                    retired ◄─┘
```

| Transición | Quién | Condición mínima |
|------------|-------|------------------|
| candidate → validated | sistema | walk-forward completo, ≥ 200 operaciones de test, expectancy neta > baseline en la mayoría de ventanas, drawdown ≤ baseline × 1.2 |
| validated → approved | humano (dashboard/n8n) | revisa reporte |
| approved → active | humano, con confirmación | solo un modelo activo por símbolo/timeframe |
| active → retired | humano o vencimiento | `expires_at` vencido o degradación en paper |
| cualquiera → rejected | sistema o humano | falla criterios |

- **Nunca** se activa un modelo automáticamente, aunque mejore el beneficio total.
- Cada modelo guarda `ModelRecord` (ver `architecture.md` §5.5) + hash del artefacto + hash del dataset.
- Un modelo cuyo hash de artefacto no coincide con el registry no se carga.
