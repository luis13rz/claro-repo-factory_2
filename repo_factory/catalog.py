"""Catálogo de repos creados (catalog/jobs.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import ROOT

CATALOG_PATH = ROOT / "catalog" / "jobs.yaml"
KEYS = ("job_name", "repo", "owner_team", "cost_center", "tech_lead", "requested_by", "issue", "created_at")


class CatalogError(ValueError):
    """Catálogo inválido o entrada duplicada."""


def load(path: Path | None = None) -> list[dict]:
    path = path or CATALOG_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("jobs"), list):
        raise CatalogError(f"{path}: se espera 'version: 1' y una lista 'jobs'")
    names, repos = [e.get("job_name") for e in data["jobs"]], [e.get("repo") for e in data["jobs"]]
    if len(set(names)) != len(names) or len(set(repos)) != len(repos):
        raise CatalogError(f"{path}: hay job_name o repo duplicados")
    for e in data["jobs"]:
        if set(e) != set(KEYS):
            raise CatalogError(f"{path}: la entrada {e.get('job_name')!r} debe tener exactamente {list(KEYS)}")
    return data["jobs"]


def names_and_repos(entries: list[dict]) -> tuple[set[str], set[str]]:
    return {e["job_name"] for e in entries}, {e["repo"] for e in entries}


def add(entry: dict, path: Path | None = None) -> bool:
    """Agrega la entrada. Devuelve False si ya estaba idéntica (reintento idempotente)."""
    path = path or CATALOG_PATH
    entries = load(path)
    for e in entries:
        if e["job_name"] == entry["job_name"] or e["repo"] == entry["repo"]:
            if e == entry:
                return False
            raise CatalogError(f"ya existe una entrada distinta para {entry['job_name']!r}")
    entries.append(entry)
    entries.sort(key=lambda e: e["job_name"])
    header = ("# Catálogo de repos creados por el servicio (lo actualiza el workflow create-repo; no editar a mano).\n")
    path.write_text(header + yaml.safe_dump({"version": 1, "jobs": entries}, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return True
