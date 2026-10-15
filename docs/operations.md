# Operaciones

## Grabación macro en Azure (Crucix + grabador)

| Recurso | Valor |
|---------|-------|
| Suscripción | Azure for Students (crédito; **sin tarjeta, no puede cobrar dinero real**) |
| Grupo de recursos | `rg-itp-macro` (Spain Central, única región permitida con capacidad) |
| VM | `vm-itp-macro`, Ubuntu 24.04, `Standard_B2ats_v2` (2 vCPU, 1 GB) + 2 GB swap, disco 64 GB P6 |
| Red | IP pública solo para salida; **sin reglas de entrada** (ni SSH). Administración con `az vm run-command` |
| App | `/opt/itp/app` (clon del repo), compose `infra/docker/docker-compose.macro.yml` |
| Datos | `/opt/itp/app/infra/docker/data/macro_snapshots/*.jsonl` |
| Secretos | `infra/docker/crucix.env` en la VM (modo 600, solo `FRED_API_KEY`) |
| Presupuesto | `itp-monthly`: 10 USD/mes, correo a 50 % y 100 % |

Costo esperado: la VM B2ats v2 y el disco P6 entran en los servicios gratuitos de estudiante (750 h/mes); la IP pública consume ~3-4 USD/mes de crédito.

### Comandos (desde la raíz del repo, en PowerShell)

```powershell
# Estado: contenedores, últimos snapshots, memoria y disco
az vm run-command invoke -g rg-itp-macro -n vm-itp-macro --command-id RunShellScript `
  --scripts "@infra/azure/status-macro.sh" --query "value[0].message" -o tsv

# Desplegar / actualizar (lee la clave FRED del .env local de Crucix sin mostrarla)
$k = ((Select-String -Path $env:USERPROFILE\Desktop\Crucix\.env -Pattern '^FRED_API_KEY=(.*)$').Matches[0].Groups[1].Value).Trim()
az vm run-command invoke -g rg-itp-macro -n vm-itp-macro --command-id RunShellScript `
  --scripts "@infra/azure/deploy-macro.sh" --parameters $k main --query "value[0].message" -o tsv

# Pausar para ahorrar crédito (deja de grabar; "deallocate" detiene el cobro de cómputo)
az vm deallocate -g rg-itp-macro -n vm-itp-macro
az vm start -g rg-itp-macro -n vm-itp-macro   # los contenedores arrancan solos

# Borrar todo (irreversible: se pierden los snapshots no descargados)
az group delete -n rg-itp-macro
```

`az vm run-command` devuelve como máximo ~4 KB de salida: sirve para administrar, no para descargar datos.

### Lecciones del primer despliegue (2026-10-12)

- `Standard_B1s` sin capacidad en Spain Central (`SkuNotAvailable`); B2ats v2 validó y también es gratuita.
- `az` en Windows no pasa bien scripts multilínea por `--scripts "..."`: usar archivos (`--scripts @archivo.sh`).
- El repo en la VM es de `azureuser` y run-command corre como root: git necesita `safe.directory` (lo pone el script).
- El contenedor del grabador debe usar el mismo uid que el dueño de la carpeta montada (1000).
- Crucix necesita ~400 MB de heap de JS por barrido: con `mem_limit: 512m` entraba en bucle de "heap out of memory". Ahora 1 GB y `--max-old-space-size=768`.

## Grabación en el PC (desactivada 2026-10-12)

Azure quedó como único grabador: las tareas `ITP-Crucix` e `ITP-MacroRecorder` se eliminaron (eran frágiles: se caían al detener procesos desde la terminal de Claude). Los snapshots ya grabados en `research/macro_snapshots/` se conservan. Para reactivarlas: `.\infra\windows\register-tasks.ps1`.

## Pendiente

- Descarga de snapshots de Azure al PC para los backtests (abrir SSH temporal solo desde tu IP y `scp`, o subir a Blob Storage).
- Respaldo periódico de los snapshots fuera de la VM.

## Paper trading en el PC (Fase 7, ADR 0016)

- Tarea `ITP-PaperTick` (por usuario, sin admin): ejecuta `infra/windows/paper-tick.ps1` cada 5 minutos mientras la sesión está abierta. Cada corrida procesa solo las velas H4 cerradas nuevas. **No envía órdenes.**
- Estado en `data/paper/paper.db` (SQLite, fuera de git) del checkout principal. Log mensual en `%LOCALAPPDATA%\itp\logs\paper-tick-AAAA-MM.log`.
- Registrar: `.\infra\windows\register-paper-task.ps1` (con `-SrcDir <ruta>\src` para correr código de una rama todavía sin merge). Quitar: `-Unregister`.
- Reporte y paridad con el backtest: `.\.venv\Scripts\python.exe -m trading_system.cli paper report` (`--no-parity` si MT5 no está disponible).
- Si el PC está apagado al cierre de una vela H4, la entrada queda como `missed_late` y la salida por canal se registra al cierre como tardía. Con `stale_data`, MT5 no estaba sincronizado y no se decidió nada: se reintenta en la siguiente corrida.
