"""Creación del repo paso a paso. Cada paso es idempotente: si algo falla, se corrige y se re-aprueba sin duplicar nada."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import FactoryConfig
from .customize import SKIP_CI, customize_all
from .github import GitHubClient, GitHubError
from .request import JobRequest
from .validation import Problem

FILES_TO_READ = ("job.config.yaml", "databricks.yml", "README.md")
READY_TRIES, READY_WAIT = 10, 3.0


class ProvisionError(RuntimeError):
    """Un paso no pudo completarse."""


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    detail: str = ""


def marker_topic(issue_number: int) -> str:
    return f"factory-issue-{issue_number}"


def preflight(req: JobRequest, cfg: FactoryConfig, gh: GitHubClient) -> list[Problem]:
    """Verificaciones que requieren la API: equipos, usuario, repo existente y plantilla."""
    p: list[Problem] = []
    template = gh.get_repo(cfg.org, cfg.template_repo)
    if template is None or not template.get("is_template"):
        p.append(Problem("configuración", f"{cfg.org}/{cfg.template_repo} no existe o no es un 'Template repository'"))
    for slug in {cfg.platform_team, *cfg.approver_teams, *cfg.prod_reviewer_teams}:
        if gh.get_team(cfg.org, slug) is None:
            p.append(Problem("configuración", f"el equipo {slug!r} de factory.yaml no existe en {cfg.org}"))
    if gh.get_team(cfg.org, req.owner_team) is None:
        p.append(Problem("owner_team", f"el equipo {req.owner_team!r} no existe en {cfg.org}"))
    elif not gh.user_exists(req.tech_lead):
        p.append(Problem("tech_lead", f"el usuario de GitHub {req.tech_lead!r} no existe"))
    elif not gh.is_team_member(cfg.org, req.owner_team, req.tech_lead):
        p.append(Problem("tech_lead", f"{req.tech_lead!r} no pertenece al equipo {req.owner_team!r}"))
    repo = cfg.repo_name(req.job_name)
    if gh.get_repo(cfg.org, repo) is not None and marker_topic(req.issue_number) not in gh.get_topics(cfg.org, repo):
        p.append(Problem("job_name", f"el repo {repo!r} ya existe y no fue creado por esta solicitud"))
    return p


def provision(req: JobRequest, cfg: FactoryConfig, gh: GitHubClient, *,
              sleep: Callable[[float], None] = time.sleep) -> list[Step]:
    org, repo, branch = cfg.org, cfg.repo_name(req.job_name), cfg.default_branch
    steps: list[Step] = []

    def create_repo() -> str:
        if gh.get_repo(org, repo) is not None:
            if marker_topic(req.issue_number) not in gh.get_topics(org, repo):
                raise ProvisionError(f"{repo} ya existe y no fue creado por la solicitud #{req.issue_number}")
            return "ya existía (reintento de esta solicitud)"
        gh.generate_from_template(org, cfg.template_repo, org, repo, req.description)
        gh.set_topics(org, repo, ["databricks-job", marker_topic(req.issue_number)])  # marca para reintentos
        return f"{org}/{repo} (privado)"

    def wait_ready() -> str:
        for _ in range(READY_TRIES):
            if gh.get_file(org, repo, "job.config.yaml", branch) is not None:
                return "contenido listo"
            sleep(READY_WAIT)
        raise ProvisionError("la plantilla no terminó de generarse a tiempo; reintenta la aprobación")

    def customize() -> str:
        current = {}
        for path in (*FILES_TO_READ, ".github/CODEOWNERS"):
            text = gh.get_file(org, repo, path, branch)
            if text is None and path in FILES_TO_READ:
                raise ProvisionError(f"la plantilla no tiene {path}")
            current[path] = text or ""
        final = customize_all({k: current[k] for k in FILES_TO_READ}, req, cfg)
        changed = {p: c for p, c in final.items() if current.get(p) != c}
        if not changed:
            return "sin cambios (ya estaba personalizado)"
        gh.commit_files(org, repo, branch, f"Configura el repo desde la solicitud #{req.issue_number} {SKIP_CI}", changed)
        return "commit único: " + ", ".join(sorted(changed))

    def branches() -> str:
        head = gh.branch_sha(org, repo, branch)
        created = []
        for b in cfg.branches:
            if b != branch and gh.branch_sha(org, repo, b) is None:
                gh.create_branch(org, repo, b, head)  # type: ignore[arg-type]
                created.append(b)
        return f"ramas {list(cfg.branches)} (nuevas: {created or 'ninguna'})"

    def environments() -> str:
        ids = []
        for slug in cfg.prod_reviewer_teams:
            team = gh.get_team(org, slug)
            if team is None:
                raise ProvisionError(f"el equipo revisor {slug!r} no existe")
            ids.append(team["id"])
        for b in cfg.branches:
            gh.put_environment(org, repo, b, reviewer_team_ids=ids if b in cfg.approval_environments else [], branch=b)
        return f"environments {list(cfg.branches)}; con aprobación: {list(cfg.approval_environments)}"

    def protection() -> str:
        for b in cfg.branches:
            gh.protect_branch(org, repo, b, checks=list(cfg.required_checks), approvals=cfg.required_approvals)
        return f"protección en {list(cfg.branches)}"

    def teams() -> str:
        gh.add_team_repo(org, req.owner_team, org, repo, "push")
        gh.add_team_repo(org, cfg.platform_team, org, repo, "admin")
        return f"{req.owner_team}: escritura; {cfg.platform_team}: admin"

    plan = [("Crear repo desde la plantilla", create_repo), ("Esperar el contenido", wait_ready),
            ("Personalizar archivos", customize), ("Crear ramas de ambiente", branches),
            ("Asignar equipos", teams),  # antes que los Environments: un revisor debe tener acceso al repo
            ("Configurar Environments", environments), ("Proteger ramas", protection)]
    for name, fn in plan:
        try:
            steps.append(Step(name, True, fn()))
        except (GitHubError, ProvisionError) as e:
            steps.append(Step(name, False, str(e)))
            break
    return steps


def succeeded(steps: list[Step]) -> bool:
    return bool(steps) and all(s.ok for s in steps)
