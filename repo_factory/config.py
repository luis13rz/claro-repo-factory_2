"""Configuración de convenciones (factory.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "factory.yaml"


class ConfigError(ValueError):
    """factory.yaml inválido."""


@dataclass(frozen=True)
class FactoryConfig:
    org: str
    template_repo: str
    repo_prefix: str
    reserved_names: tuple[str, ...]
    default_branch: str
    branches: tuple[str, ...]
    workspace_root: str
    platform_team: str
    approver_teams: tuple[str, ...]
    approval_environments: tuple[str, ...]
    prod_reviewer_teams: tuple[str, ...]
    forbid_self_approval: bool
    required_checks: tuple[str, ...]
    required_approvals: int
    cluster_sizes: tuple[str, ...]
    period_modes: tuple[str, ...]
    email_domains: tuple[str, ...]
    max_alert_emails: int

    def repo_name(self, job_name: str) -> str:
        return f"{self.repo_prefix}{job_name}"

    def workspace_path(self, owner_team: str, job_name: str) -> str:
        return f"{self.workspace_root.rstrip('/')}/{owner_team}/{job_name}"


_STR = ("org", "template_repo", "repo_prefix", "default_branch", "workspace_root", "platform_team")
_LISTS = ("reserved_names", "branches", "approver_teams", "approval_environments", "prod_reviewer_teams", "required_checks",
          "cluster_sizes", "period_modes", "email_domains")
_BOOL = ("forbid_self_approval",)
_INT = ("required_approvals", "max_alert_emails")


def load_config(path: Path | None = None) -> FactoryConfig:
    path = path or Path(os.getenv("FACTORY_CONFIG", DEFAULT_PATH))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: se espera un mapa YAML")
    known = set(_STR) | set(_LISTS) | set(_BOOL) | set(_INT)
    missing, extra = sorted(known - set(data)), sorted(set(data) - known)
    if missing or extra:
        raise ConfigError(f"{path}: faltan {missing}, sobran {extra}")
    for k in _STR:
        if not isinstance(data[k], str) or not data[k].strip():
            raise ConfigError(f"{k} debe ser texto no vacío")
    for k in _LISTS:
        v = data[k]
        if not isinstance(v, list) or not v and k not in ("reserved_names",) or not all(isinstance(i, str) for i in v):
            raise ConfigError(f"{k} debe ser una lista de textos{' no vacía' if k != 'reserved_names' else ''}")
    for k in _BOOL:
        if not isinstance(data[k], bool):
            raise ConfigError(f"{k} debe ser true/false")
    for k in _INT:
        if not isinstance(data[k], int) or isinstance(data[k], bool) or data[k] < 1:
            raise ConfigError(f"{k} debe ser un entero >= 1")
    if data["default_branch"] not in data["branches"]:
        raise ConfigError("default_branch debe estar en branches")
    if not set(data["approval_environments"]) <= set(data["branches"]):
        raise ConfigError("approval_environments debe ser un subconjunto de branches")
    if any(b != b.lower() for b in data["branches"]):
        raise ConfigError("las ramas de ambiente van en minúsculas")
    if not data["workspace_root"].startswith("/Workspace/"):
        raise ConfigError("workspace_root debe iniciar con /Workspace/")
    return FactoryConfig(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in data.items()})
