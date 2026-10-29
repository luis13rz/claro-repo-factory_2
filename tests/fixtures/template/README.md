# <nombre-del-job>

Repo de un job de Databricks. **El pipeline de CI/CD no vive aquí**: lo ejecuta el workflow reutilizable de
`claro-databricks-platform`. Este repo solo aporta código y configuración.

| Archivo | Quién lo edita | Para qué |
|---|---|---|
| `job.config.yaml` | Equipo dueño | Define el job: schedule, talla de cluster, tasks, quality gate, notificaciones |
| `src/` | Equipo dueño | Notebooks del proceso |
| `databricks.yml` | Plataforma | Bundle estándar (solo cambia `bundle.name` al crear el repo) |
| `.github/` | Plataforma | Llamador del pipeline (no tocar) |

## Flujo por rama

| Evento | Qué ejecuta |
|---|---|
| Push a `feature/*`, `bugfix/*` u otra rama | `quality` (sin permiso de despliegue) |
| Pull request hacia `dev` o `prod` | `quality` + `plan` (resuelve el pool y hace `bundle validate`) |
| Push o merge a `dev` | `quality` + `plan` + `deploy` a dev |
| Push o merge a `prod` | `quality` + `plan` + **aprobación manual** + `deploy` a prod |

Las ramas de ambiente se escriben en **minúsculas** (`dev`, `prod`), igual que los targets y los GitHub Environments.
Una rama `Dev` o `Prod` hace fallar el pipeline a propósito. No hay secretos: GitHub se autentica con OIDC.

## Resultado de cada ejecución del job

El job registra en la tabla de control un estado distinto para cada caso, de modo que un job omitido no se confunde con uno exitoso:

| Caso | `status` en la tabla de control | Task que lo registra |
|---|---|---|
| Éxito | `SUCCESS` | `register_success` |
| Falla | `FAILED` (el job queda en Failed) | `register_failure` |
| Omitido: el periodo ya estaba procesado | `SKIPPED_ALREADY_PROCESSED` | `register_skip` |
| Reproceso autorizado (`force_run=true`) | `REPROCESS_SUCCESS` | `register_success` |
| Falla al registrar el resultado | el job falla en `register_success` tras 3 reintentos | — (ver `docs/ESTADOS-DE-EJECUCION.md`) |

## Lo que se valida (y bloquea el merge)

- `job.config.yaml` cumple el esquema y las políticas (grupos de permisos, correos, sin secretos en parámetros).
- Notebooks sin `collect()` / `toPandas()` / `take(n)` grande, sin `import *`, sin `DROP`/`TRUNCATE`/`DELETE` sin `WHERE`,
  sin correos escritos en el código.
- Sin secretos (tokens, llaves, contraseñas) en el repositorio.
- `ruff`, `bandit`, `pip-audit` (si hay `requirements*.txt`) y `pytest`.

Excepción puntual y auditable: `# claro: allow CLARO001 -- motivo de al menos 10 caracteres`.

## Talla del cluster

Solo se declara `cluster.size` (por ejemplo `M`). El instance pool, el runtime y el rango de workers los resuelve
el pipeline desde la tabla de Unity Catalog de plataforma, por ambiente.

## Reproceso de un periodo ya cerrado

Lanzar el job con el parámetro `force_run=true` (solo los grupos con `can_manage_run`). Queda registrado como `REPROCESS_SUCCESS`.
