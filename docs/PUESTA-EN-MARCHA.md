# Puesta en marcha

## 1. Repo plantilla

En `ClaroCENAM/template-databricks-job`: Settings → marcar **Template repository**. Su **rama por defecto debe ser `dev`**
(es la que hereda cada repo nuevo; coincide con `default_branch` de `factory.yaml`).

## 2. Equipos de GitHub

Deben existir los slugs de `factory.yaml`: `platform-team` (aprobadores, revisores de `prod`, admin de todos los repos) y un equipo por
cada equipo dueño de jobs (el slug es lo que se escribe en el formulario).

## 3. GitHub App (única credencial del servicio)

La API de GitHub no tiene OIDC, así que crear repos requiere una GitHub App con permisos acotados. Es la **única excepción** a la
política "sin secretos"; por eso su llave vive solo en este repo.

Permisos sugeridos (verificar los mínimos exactos en el piloto):

| Ámbito | Permiso | Para qué |
|---|---|---|
| Repositorio | Administration: write | crear repos, proteger ramas, Environments, asignar equipos |
| Repositorio | Contents: write | el commit de personalización y las ramas |
| Repositorio | Issues: write | comentar, etiquetar y cerrar solicitudes |
| Repositorio | Metadata: read | obligatorio |
| Organización | Members: read | comprobar equipos y membresías |

Instalarla en la organización con acceso a **todos los repos** (necesita crear repos nuevos y leer la plantilla).

## 4. Este repo

1. Crear el repo `ClaroCENAM/claro-repo-factory` y subir el contenido; rama por defecto `main`.
2. **Environment `repo-factory`** con *deployment branches* restringido a `main`. Dentro:
   - variable `FACTORY_APP_ID`;
   - secreto `FACTORY_APP_PRIVATE_KEY` (la llave privada de la App).
3. Proteger `main` (PR + revisión) y agregar la App a la lista de *bypass*: el workflow le hace push al catálogo.
4. Las etiquetas (`solicitud-repo`, `validada`, `invalida`, `aprobado`, `creada`) se crean solas en la primera validación.
5. Restringir quién puede agregar etiquetas (rol *Triage*) a los integrantes de `platform-team`: es defensa extra; la autorización real
   la comprueba el programa.

## 5. Primera prueba (con un repo de mentira)

1. Abrir un issue con el formulario usando el nombre `prueba-fabrica` y un equipo real. Verificar el comentario ✅.
2. Con otra persona de `platform-team`, agregar `aprobado`.
3. Revisar el repo `job-prueba-fabrica`: ramas, protecciones, Environments, equipos, `job.config.yaml`.
4. Abrir un PR de prueba hacia `dev` y comprobar que corre el pipeline y **cómo se llama el check**; ajustar `required_checks` si no es
   `pipeline / quality`.
5. Borrar el repo de prueba y su entrada del catálogo.
