"""Personalización de los archivos de la plantilla para un repo nuevo. Funciones puras e idempotentes."""
from __future__ import annotations

import io

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import FactoryConfig
from .request import JobRequest

SKIP_CI = "[skip ci]"   # el commit inicial no debe disparar el pipeline: el repo aún no tiene sus Environments
MARKER = "<!-- repo-factory -->"


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _dump(data) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def customize_job_config(text: str, req: JobRequest) -> str:
    """Pone los datos del formulario y quita los ejemplos que no existen en el ambiente real
    (grupos, tablas del quality gate, parámetros): evitarían que el primer despliegue funcione."""
    doc = _yaml().load(text)
    job = doc["job"]
    job["name"] = req.job_name
    job["description"] = req.description
    job["owner_team"] = req.owner_team
    job["cost_center"] = req.cost_center
    job["period_mode"] = req.period_mode
    job["cluster"]["size"] = req.cluster_size
    emails = CommentedSeq(req.alert_emails)
    emails.fa.set_flow_style()
    job["notifications"]["on_failure"] = emails
    if req.schedule_cron:
        if "schedule" not in job:
            job["schedule"] = CommentedMap()
        job["schedule"]["cron"] = req.schedule_cron
    else:
        job.pop("schedule", None)
    for sample in ("permissions", "parameters", "quality_gate"):
        job.pop(sample, None)
    return _dump(doc)


def customize_bundle(text: str, req: JobRequest, cfg: FactoryConfig) -> str:
    """bundle.name = nombre del job; ruta de despliegue estandarizada por equipo/job/ambiente."""
    doc = _yaml().load(text)
    doc["bundle"]["name"] = req.job_name
    root = f"{cfg.workspace_path(req.owner_team, req.job_name)}/${{bundle.target}}"
    for target in doc.get("targets", {}).values():
        target["workspace"]["root_path"] = root
    return _dump(doc)


def build_codeowners(req: JobRequest, cfg: FactoryConfig) -> str:
    plat, own = f"@{cfg.org}/{cfg.platform_team}", f"@{cfg.org}/{req.owner_team}"
    return (
        "# El equipo de plataforma controla el pipeline y el bundle; el equipo dueño controla su lógica.\n"
        f"/.github/         {plat}\n"
        f"/databricks.yml   {plat}\n"
        f"/job.config.yaml  {plat} {own}\n"
        f"/src/             {own} @{req.tech_lead}\n"
    )


def customize_readme(text: str, req: JobRequest, cfg: FactoryConfig) -> str:
    if MARKER in text:  # ya personalizado (reintento)
        return text
    header = (
        f"# {req.job_name}\n\n{MARKER}\n"
        f"{req.description}\n\n"
        "| | |\n|---|---|\n"
        f"| Equipo dueño | `{req.owner_team}` |\n"
        f"| Responsable técnico | @{req.tech_lead} |\n"
        f"| Centro de costo | `{req.cost_center}` |\n"
        f"| Ruta en el workspace | `{cfg.workspace_path(req.owner_team, req.job_name)}/<ambiente>` |\n"
        f"| Solicitud | #{req.issue_number} (repo de fábrica) |\n\n"
        "### Primeros pasos\n\n"
        "1. Reemplaza `src/notebooks/main.py` por la lógica del job y ajusta `tasks` en `job.config.yaml`.\n"
        "2. Agrega `quality_gate`, `permissions` y `parameters` en `job.config.yaml` cuando los necesites "
        "(el formulario no los pide).\n"
        "3. Abre un pull request hacia `dev`: el pipeline valida y planifica sin desplegar.\n\n---\n\n"
    )
    body = text.split("\n", 1)[1].lstrip("\n") if text.startswith("# ") else text
    return header + body


def customize_all(files: dict[str, str], req: JobRequest, cfg: FactoryConfig) -> dict[str, str]:
    """files: contenido actual de job.config.yaml, databricks.yml y README.md -> contenido final de los 4 archivos."""
    return {
        "job.config.yaml": customize_job_config(files["job.config.yaml"], req),
        "databricks.yml": customize_bundle(files["databricks.yml"], req, cfg),
        ".github/CODEOWNERS": build_codeowners(req, cfg),
        "README.md": customize_readme(files["README.md"], req, cfg),
    }
