"""Validación pura (sin red) de una solicitud contra las convenciones de factory.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FactoryConfig
from .request import OPTIONAL, JobRequest, RawRequest, confirmations_ok

JOB_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")   # kebab-case: sin guiones dobles ni al final
TEAM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
COST_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
MIN_NAME, MAX_NAME = 3, 50


@dataclass(frozen=True)
class Problem:
    field: str
    message: str


def check_quartz(expr: str) -> str | None:
    """Misma regla que platform-ci (copiada a propósito: este repo no depende del paquete de plataforma)."""
    parts = expr.split()
    if len(parts) not in (6, 7):
        return f"el cron Quartz debe tener 6 o 7 campos y tiene {len(parts)}"
    if (parts[3] == "?") == (parts[5] == "?"):
        return "en Quartz exactamente uno de día-del-mes / día-de-semana debe ser '?'"
    return None


def validate_request(raw: RawRequest, cfg: FactoryConfig, *, issue_number: int, requester: str,
                     existing_jobs: set[str] = frozenset(),
                     existing_repos: set[str] = frozenset()) -> tuple[JobRequest | None, list[Problem]]:
    p: list[Problem] = []

    def bad(field: str, msg: str) -> None:
        p.append(Problem(field, msg))

    if raw.missing or raw.unknown:
        bad("formulario", "El cuerpo del issue no corresponde al formulario (se editaron o borraron secciones). "
                          "Crea un issue nuevo con la plantilla. "
                          f"Faltan: {raw.missing or '-'}; no reconocidas: {raw.unknown or '-'}.")
        return None, p

    f = raw.fields
    for key, value in f.items():
        if key not in OPTIONAL and key != "confirmations" and not value:
            bad(key, "es obligatorio")
    if p:
        return None, p

    for key, value in f.items():
        if key != "confirmations" and ("\n" in value or CONTROL_CHARS.search(value)):
            bad(key, "no puede tener saltos de línea ni caracteres de control")

    name = f["job_name"]
    if not JOB_NAME_RE.match(name) or not (MIN_NAME <= len(name) <= MAX_NAME):
        bad("job_name", f"debe ser kebab-case en minúsculas ({MIN_NAME}-{MAX_NAME} caracteres), sin guiones "
                        "dobles ni al inicio/fin, y empezar con letra. Ej.: parque-imei-regional")
    elif name in cfg.reserved_names:
        bad("job_name", f"{name!r} es un nombre reservado")
    elif name in existing_jobs:
        bad("job_name", f"ya existe un job registrado con el nombre {name!r}")
    elif cfg.repo_name(name) in existing_repos:
        bad("job_name", f"ya existe el repo {cfg.repo_name(name)!r}")

    if not TEAM_RE.match(f["owner_team"]):
        bad("owner_team", "debe ser el slug del equipo de GitHub (minúsculas, números, '.', '_' o '-')")
    if not COST_RE.match(f["cost_center"]):
        bad("cost_center", "formato inválido (letras, números, '_' o '-', 2 a 32 caracteres)")
    if not 10 <= len(f["description"]) <= 500:
        bad("description", "debe tener entre 10 y 500 caracteres")
    if f["cluster_size"] not in cfg.cluster_sizes:
        bad("cluster_size", f"debe ser una de {list(cfg.cluster_sizes)}")
    if f["period_mode"] not in cfg.period_modes:
        bad("period_mode", f"debe ser uno de {list(cfg.period_modes)}")
    cron = f["schedule_cron"].strip()
    if cron and (msg := check_quartz(cron)):
        bad("schedule_cron", msg)

    emails = [e.strip() for e in re.split(r"[,\s]+", f["alert_emails"]) if e.strip()]
    if not emails or len(emails) > cfg.max_alert_emails or len(set(emails)) != len(emails):
        bad("alert_emails", f"indica de 1 a {cfg.max_alert_emails} correos distintos")
    for e in emails:
        m = EMAIL_RE.match(e)
        if not m:
            bad("alert_emails", f"{e!r} no es un correo válido")
        elif m.group(1).lower() not in cfg.email_domains:
            bad("alert_emails", f"{e!r}: el dominio debe ser uno de {list(cfg.email_domains)}")

    tech = f["tech_lead"].lstrip("@")
    if not USER_RE.match(tech):
        bad("tech_lead", "debe ser un usuario de GitHub válido (sin @)")
    if not confirmations_ok(f["confirmations"]):
        bad("confirmations", "debes marcar las 3 confirmaciones")

    if p:
        return None, p
    return JobRequest(name, f["owner_team"], f["cost_center"], f["description"].strip(), f["cluster_size"],
                      f["period_mode"], cron or None, tuple(emails), tech, issue_number, requester), []
