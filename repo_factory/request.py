"""Lectura del cuerpo de un issue creado con el formulario (issue form)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Etiqueta del formulario -> campo. DEBE coincidir con .github/ISSUE_TEMPLATE/solicitud-repo-job.yml (hay un test).
LABELS = {
    "Nombre del job": "job_name",
    "Equipo dueño (slug del equipo de GitHub)": "owner_team",
    "Centro de costo": "cost_center",
    "Descripción": "description",
    "Talla de cluster": "cluster_size",
    "Modo de periodo": "period_mode",
    "Schedule (cron Quartz, opcional)": "schedule_cron",
    "Correos de alerta": "alert_emails",
    "Responsable técnico (usuario de GitHub)": "tech_lead",
    "Confirmaciones": "confirmations",
}
OPTIONAL = {"schedule_cron"}
EXPECTED_CONFIRMATIONS = 3
NO_RESPONSE = "_No response_"
HEADING = re.compile(r"^### (.+?)\s*$")
CHECKBOX = re.compile(r"^- \[( |x|X)\] .+")


@dataclass(frozen=True)
class RawRequest:
    fields: dict[str, str]
    missing: list[str]       # secciones del formulario que no aparecen (formulario alterado)
    unknown: list[str]       # secciones que no existen en el formulario


def parse_issue_body(body: str | None) -> RawRequest:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = HEADING.match(line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    fields: dict[str, str] = {}
    unknown: list[str] = []
    for label, lines in sections.items():
        value = "\n".join(lines).strip()
        if value == NO_RESPONSE:
            value = ""
        key = LABELS.get(label)
        if key is None:
            unknown.append(label)
        else:
            fields[key] = value
    missing = [label for label, key in LABELS.items() if key not in fields]
    return RawRequest(fields, missing, unknown)


def confirmations_ok(text: str) -> bool:
    boxes = [ln.strip() for ln in text.splitlines() if CHECKBOX.match(ln.strip())]
    return len(boxes) == EXPECTED_CONFIRMATIONS and all(b[3] in "xX" for b in boxes)


@dataclass(frozen=True)
class JobRequest:
    job_name: str
    owner_team: str
    cost_center: str
    description: str
    cluster_size: str
    period_mode: str
    schedule_cron: str | None
    alert_emails: tuple[str, ...]
    tech_lead: str
    issue_number: int
    requester: str
