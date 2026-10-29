# claro-repo-factory

Servicio de creación estandarizada de repos de jobs de Databricks: **alguien abre un issue con un formulario, plataforma lo aprueba
con una etiqueta, y el repo se crea solo** con el nombre, la estructura y las protecciones correctas. Nadie configura repos a mano.

```
 ① Issue (formulario)      ② validate-request            ③ aprobación              ④ create-repo
 ┌──────────────────┐     ┌────────────────────┐       ┌──────────────────┐     ┌──────────────────────────────┐
 │ nombre, equipo,  │ ──▶ │ formato, duplicados│ ──▶   │ integrante de    │ ──▶ │ repo desde la plantilla      │
 │ costo, talla,    │     │ equipo/usuario     │       │ platform-team    │     │ + personaliza archivos       │
 │ schedule, correos│     │ existen (API)      │       │ pone `aprobado`  │     │ + ramas dev/prod + protección│
 └──────────────────┘     │ → ✅ validada / ❌ │       │ (≠ quien pidió)  │     │ + Environments + equipos     │
                          └────────────────────┘       └──────────────────┘     │ + catálogo + cierra el issue │
                                                                                └──────────────────────────────┘
```

## Qué recibe el usuario

Un repo **privado** `job-<nombre-del-job>` con:
- `job.config.yaml` ya llenado con los datos del formulario (nombre, equipo, centro de costo, talla, periodo, schedule, alertas);
- `databricks.yml` con `bundle.name` y la ruta de despliegue estandarizada `/Workspace/Shared/jobs/<equipo>/<job>/<ambiente>`;
- ramas `dev` y `prod`, protegidas (PR obligatorio, 1 aprobación, code owners, check del pipeline, sin force-push);
- GitHub Environments `dev` y `prod` (en `prod`, aprobación manual y despliegue solo desde la rama `prod`);
- `CODEOWNERS` (plataforma controla `.github/` y `databricks.yml`; el equipo dueño su código), y permisos de equipos;
- el llamador del pipeline central (`@v1`) que trae la plantilla.

El commit inicial lleva `[skip ci]`: el repo no despliega nada hasta que su dueño abra el primer PR.

## Convenciones (editar `factory.yaml`, con PR revisado)

| Tema | Regla actual |
|---|---|
| Nombre del job | kebab-case, 3-50 caracteres, sin `--`, no reservado (`template`, `demo`, ...) |
| Nombre del repo | `job-<nombre-del-job>` (`repo_prefix`) |
| Ramas de ambiente | `dev`, `prod`, siempre en minúsculas |
| Ruta en el workspace | `/Workspace/Shared/jobs/<equipo-dueño>/<job>/<ambiente>` (`workspace_root`) |
| Tallas de cluster | `XS, S, M, L, XL` (deben existir en la tabla `cluster_pools`) |
| Correos de alerta | 1 a 5, del dominio `claro.com.gt` |
| Aprobadores | `platform-team`; quien solicita **no** puede aprobar su propia solicitud |

## Garantías de seguridad

- El contenido del issue es **entrada no confiable**: nunca se interpola en un comando; el programa lo lee del JSON del evento y lo valida con
  expresiones estrictas. Los valores viajan a la API como JSON y al YAML con un serializador, no por texto.
- Editar el issue después de aprobarlo **invalida la aprobación**, y al crear se **revalida** con el contenido vigente.
- Solo integrantes de `approver_teams` aprueban; ni quien solicita ni cuentas externas.
- Los secretos (llave de la GitHub App) viven en el Environment `repo-factory`, restringido a la rama `main`: los workflows de `issues` corren desde `main`.
- Cada paso de creación es **idempotente**: si falla uno, el comentario del issue dice cuál y por qué; se corrige la causa, se quita y se vuelve a poner
  `aprobado`, y continúa sin duplicar nada (el repo queda marcado con el tema `factory-issue-<n>`).
- Un repo existente que no fue creado por la misma solicitud **nunca se toca**.

## Operación

| Situación | Qué pasa |
|---|---|
| Datos con errores | El validador comenta qué campo falla y pone `invalida`; al editar el issue se revalida solo |
| Aprobación de alguien no autorizado o del mismo solicitante | Se rechaza, se quita `aprobado` y se explica en el issue |
| Falla un paso (ej. el plan de GitHub no soporta protección en repos privados) | Run en rojo + comentario con los pasos ✅/❌; reintento re-aprobando |
| Éxito | Comentario con el enlace, etiqueta `creada`, entrada en `catalog/jobs.yaml` y el issue se cierra |

`catalog/jobs.yaml` es el registro de todos los repos creados (job, repo, equipo, responsable, issue, fecha).

## Puesta en marcha

Ver [`docs/PUESTA-EN-MARCHA.md`](docs/PUESTA-EN-MARCHA.md): GitHub App, Environment, plantilla, equipos y primera prueba.

## Desarrollo local

```bash
pip install -e ".[dev]"
pytest -q        # 116 pruebas, con un GitHub falso en memoria
ruff check .
```

## Lo que NO hace (todavía)

- No crea nada en Databricks (service principals, pools, tablas): eso es de `claro-databricks-platform`.
- No sincroniza repos ya creados si cambia la plantilla (un cambio de estándar se propaga con PRs o con una herramienta aparte).
- No archiva ni elimina repos. La **baja** de un job es un proceso manual por ahora.

## A validar en el piloto

- El nombre exacto del check requerido (`pipeline / quality`) tal como lo muestra GitHub para un workflow reutilizable.
- Que el plan de GitHub de la organización soporte Environments con revisores y protección de ramas en repos **privados**.
- Los permisos mínimos exactos de la GitHub App (ver la guía).
- Que `[skip ci]` evite el primer pipeline en su organización, y el tiempo real que tarda la plantilla en generarse (hoy espera hasta 30 s).
