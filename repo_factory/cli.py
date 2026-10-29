"""Comandos que ejecutan los workflows: validate | create | close."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import catalog
from .config import FactoryConfig, load_config
from .github import GitHubClient, urllib_transport
from .provision import Step, preflight, provision, succeeded
from .request import JobRequest, parse_issue_body
from .validation import Problem, validate_request

LABELS = {
    "solicitud-repo": ("0E8A16", "Solicitud de creación de repo"),
    "validada": ("0075CA", "La solicitud pasó la validación automática"),
    "invalida": ("D93F0B", "La solicitud tiene errores; corrige el issue"),
    "aprobado": ("5319E7", "Aprobada por plataforma: dispara la creación del repo"),
    "creada": ("0E8A16", "El repo ya fue creado"),
}
VALIDATION_MARK = "<!-- repo-factory:validation -->"
RESULT_MARK = "<!-- repo-factory:result -->"


# ---------------------------------------------------------------- utilidades
def _client() -> GitHubClient:
    token = os.getenv("GH_TOKEN", "")
    if not token:
        raise SystemExit("::error::Falta GH_TOKEN (token de la GitHub App)")
    return GitHubClient(urllib_transport(token))


def _factory_repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def _read_event(path: str | None) -> dict:
    return json.loads(Path(path or os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))


def _label_names(issue: dict) -> set[str]:
    return {lb["name"] for lb in issue.get("labels", [])}


def _output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def upsert_comment(gh: GitHubClient, repo: str, number: int, marker: str, body: str) -> None:
    text = f"{marker}\n{body}"
    for c in gh.list_comments(repo, number):
        if c.get("body", "").startswith(marker):
            gh.update_comment(repo, c["id"], text)
            return
    gh.create_comment(repo, number, text)


def set_state_label(gh: GitHubClient, repo: str, number: int, keep: str | None, drop: tuple[str, ...]) -> None:
    for lb in drop:
        gh.remove_label(repo, number, lb)
    if keep:
        gh.add_labels(repo, number, [keep])


def _problems_md(problems: list[Problem]) -> str:
    return "\n".join(f"- **{p.field}**: {p.message}" for p in problems)


def _summary_md(req: JobRequest, cfg: FactoryConfig) -> str:
    rows = [
        ("Repo", f"`{cfg.org}/{cfg.repo_name(req.job_name)}` (privado)"),
        ("Job", f"`{req.job_name}`"), ("Equipo dueño", f"`{req.owner_team}`"),
        ("Responsable técnico", f"@{req.tech_lead}"), ("Centro de costo", f"`{req.cost_center}`"),
        ("Talla de cluster", f"`{req.cluster_size}`"), ("Modo de periodo", f"`{req.period_mode}`"),
        ("Schedule", f"`{req.schedule_cron}`" if req.schedule_cron else "sin schedule"),
        ("Alertas", ", ".join(f"`{e}`" for e in req.alert_emails)),
        ("Ruta en el workspace", f"`{cfg.workspace_path(req.owner_team, req.job_name)}/<ambiente>`"),
    ]
    return "| | |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)


def _steps_md(steps: list[Step]) -> str:
    return "\n".join(f"- {'✅' if s.ok else '❌'} **{s.name}**: {s.detail}" for s in steps)


def _check(issue: dict, cfg: FactoryConfig, gh: GitHubClient) -> tuple[JobRequest | None, list[Problem]]:
    entries = catalog.load()
    jobs, repos = catalog.names_and_repos(entries)
    req, problems = validate_request(parse_issue_body(issue.get("body")), cfg, issue_number=issue["number"],
                                     requester=issue["user"]["login"], existing_jobs=jobs, existing_repos=repos)
    if req is not None:
        problems += preflight(req, cfg, gh)
    return (req if not problems else None), problems


# ---------------------------------------------------------------- comandos
def cmd_validate(a: argparse.Namespace) -> int:
    cfg, gh, repo = load_config(), _client(), _factory_repo()
    ev = _read_event(a.event)
    issue, number = ev["issue"], ev["issue"]["number"]
    for name, (color, desc) in LABELS.items():
        gh.ensure_label(repo, name, color, desc)
    if ev.get("action") == "edited" and "aprobado" in _label_names(issue):
        gh.remove_label(repo, number, "aprobado")  # editar tras aprobar invalida la aprobación
    req, problems = _check(issue, cfg, gh)
    if req is None:
        upsert_comment(gh, repo, number, VALIDATION_MARK,
                       "### ❌ La solicitud tiene errores\n\n" + _problems_md(problems) +
                       "\n\nEdita este issue para corregirlos: se validará de nuevo automáticamente.")
        set_state_label(gh, repo, number, "invalida", ("validada",))
        return 0
    approvers = ", ".join(f"`{t}`" for t in cfg.approver_teams)
    upsert_comment(gh, repo, number, VALIDATION_MARK,
                   "### ✅ Solicitud válida\n\n" + _summary_md(req, cfg) +
                   f"\n\nUn integrante de {approvers} (distinto de quien solicita) debe agregar la etiqueta `aprobado` "
                   "para crear el repo. Si editas el issue, la aprobación se invalida.")
    set_state_label(gh, repo, number, "validada", ("invalida",))
    return 0


def cmd_create(a: argparse.Namespace) -> int:
    cfg, gh, repo = load_config(), _client(), _factory_repo()
    ev = _read_event(a.event)
    issue, number, actor = ev["issue"], ev["issue"]["number"], ev["sender"]["login"]

    def reject(msg: str) -> int:
        upsert_comment(gh, repo, number, RESULT_MARK, f"### ⛔ No se creó el repo\n\n{msg}")
        gh.remove_label(repo, number, "aprobado")
        return 0

    if not any(gh.is_team_member(cfg.org, t, actor) for t in cfg.approver_teams):
        return reject(f"@{actor} no pertenece a un equipo aprobador ({list(cfg.approver_teams)}).")
    if cfg.forbid_self_approval and actor == issue["user"]["login"]:
        return reject("Quien solicita no puede aprobar su propia solicitud.")
    if "validada" not in _label_names(issue):
        return reject("La solicitud no está validada. Espera la validación automática y vuelve a aprobar.")
    req, problems = _check(issue, cfg, gh)  # se revalida con el contenido ACTUAL del issue
    if req is None:
        return reject("La solicitud ya no es válida:\n\n" + _problems_md(problems))

    steps = provision(req, cfg, gh)
    if not succeeded(steps):
        upsert_comment(gh, repo, number, RESULT_MARK,
                       "### ❌ La creación falló\n\n" + _steps_md(steps) +
                       "\n\nLos pasos son idempotentes: corrige la causa, quita y vuelve a poner `aprobado` para reintentar.")
        gh.remove_label(repo, number, "aprobado")
        return 1
    new_repo = cfg.repo_name(req.job_name)
    catalog.add({
        "job_name": req.job_name, "repo": new_repo, "owner_team": req.owner_team, "cost_center": req.cost_center,
        "tech_lead": req.tech_lead, "requested_by": req.requester, "issue": number,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    upsert_comment(gh, repo, number, RESULT_MARK,
                   f"### ✅ Repo creado: https://github.com/{cfg.org}/{new_repo}\n\n{_steps_md(steps)}\n\n"
                   f"Aprobado por @{actor}. Siguientes pasos en el README del nuevo repo.")
    gh.add_labels(repo, number, ["creada"])
    _output("created", "true")
    return 0


def cmd_close(a: argparse.Namespace) -> int:
    gh, repo = _client(), _factory_repo()
    number = _read_event(a.event)["issue"]["number"]
    gh.close_issue(repo, number)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="repo-factory")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("validate", cmd_validate), ("create", cmd_create), ("close", cmd_close)):
        s = sub.add_parser(name)
        s.add_argument("--event", default=None, help="ruta del JSON del evento (por defecto GITHUB_EVENT_PATH)")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
