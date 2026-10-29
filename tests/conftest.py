"""GitHub falso en memoria: implementa la interfaz de GitHubClient para probar el flujo completo."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from repo_factory import catalog
from repo_factory.config import load_config
from repo_factory.github import GitHubError
from repo_factory.request import LABELS

FIXTURE = Path(__file__).parent / "fixtures" / "template"


def template_files() -> dict[str, str]:
    return {str(p.relative_to(FIXTURE)): p.read_text(encoding="utf-8") for p in FIXTURE.rglob("*") if p.is_file()}


class FakeGitHub:
    def __init__(self, ready_after: int = 0):
        self.ready_after, self.file_reads = ready_after, 0
        self.teams = {"platform-team": {"id": 1}, "oficina-de-datos": {"id": 2}}
        self.members = {("platform-team", "paula"), ("platform-team", "ana"), ("oficina-de-datos", "jperez")}
        self.users = {"paula", "ana", "jperez"}
        self.repos = {"template-databricks-job": {"is_template": True}}
        self.commits: list[dict] = []
        self.comments: list[dict] = []
        self.labels: set[str] = set()
        self.known_labels: set[str] = set()
        self.closed = False
        self.calls: list[str] = []

    # --- repos
    def get_repo(self, owner, repo):
        return self.repos.get(repo)

    def generate_from_template(self, template_owner, template_repo, owner, name, description):
        self.calls.append("generate")
        self.repos[name] = {"is_template": False, "topics": [], "description": description, "branches": {"dev": "sha0"},
                            "files": {"dev": template_files()}, "envs": {}, "protection": {}, "perms": {}}
        return self.repos[name]

    def get_topics(self, owner, repo):
        return list(self.repos[repo]["topics"])

    def set_topics(self, owner, repo, topics):
        self.repos[repo]["topics"] = list(topics)

    def get_file(self, owner, repo, path, ref):
        self.file_reads += 1
        if self.file_reads <= self.ready_after:
            return None
        return self.repos[repo]["files"][ref].get(path)

    def branch_sha(self, owner, repo, branch):
        return self.repos[repo]["branches"].get(branch)

    def commit_files(self, owner, repo, branch, message, files):
        r = self.repos[repo]
        r["files"][branch].update(files)
        sha = f"sha{len(self.commits) + 1}"
        r["branches"][branch] = sha
        self.commits.append({"message": message, "files": sorted(files), "branch": branch})
        return sha

    def create_branch(self, owner, repo, name, sha):
        self.repos[repo]["branches"][name] = sha
        self.repos[repo]["files"][name] = dict(self.repos[repo]["files"]["dev"])

    def put_environment(self, owner, repo, name, *, reviewer_team_ids, branch):
        self.repos[repo]["envs"][name] = {"reviewers": reviewer_team_ids, "branch": branch}

    def protect_branch(self, owner, repo, branch, *, checks, approvals):
        self.repos[repo]["protection"][branch] = {"checks": checks, "approvals": approvals}

    def get_team(self, org, slug):
        return self.teams.get(slug)

    def is_team_member(self, org, slug, user):
        return (slug, user) in self.members

    def user_exists(self, login):
        return login in self.users

    def add_team_repo(self, org, slug, owner, repo, permission):
        self.repos[repo]["perms"][slug] = permission

    # --- issues
    def list_comments(self, repo, number):
        return self.comments

    def create_comment(self, repo, number, body):
        self.comments.append({"id": len(self.comments) + 1, "body": body})

    def update_comment(self, repo, comment_id, body):
        next(c for c in self.comments if c["id"] == comment_id)["body"] = body

    def ensure_label(self, repo, name, color, description):
        self.known_labels.add(name)

    def add_labels(self, repo, number, labels):
        self.labels |= set(labels)

    def remove_label(self, repo, number, label):
        self.labels.discard(label)

    def close_issue(self, repo, number):
        self.closed = True


VALID_FIELDS = {
    "job_name": "parque-imei-regional", "owner_team": "oficina-de-datos", "cost_center": "CC-1234",
    "description": "Cierre mensual del parque IMEI regional", "cluster_size": "L", "period_mode": "previous_month",
    "schedule_cron": "0 0 6 1 * ?", "alert_emails": "datos-alertas@claro.com.gt", "tech_lead": "jperez",
    "confirmations": "- [x] Uno\n- [x] Dos\n- [x] Tres",
}


def issue_body(**overrides) -> str:
    """Cuerpo de issue tal como lo genera GitHub a partir del formulario."""
    values = {**VALID_FIELDS, **overrides}
    out = []
    for label, key in LABELS.items():
        v = values[key]
        out.append(f"### {label}\n\n{v if v != '' else '_No response_'}\n")
    return "\n".join(out)


def event(body: str, *, action="opened", sender="paula", requester="ana", labels=("solicitud-repo", "validada"),
          label=None, number=7) -> dict:
    ev = {"action": action, "sender": {"login": sender},
          "issue": {"number": number, "body": body, "user": {"login": requester},
                    "labels": [{"name": n} for n in labels]}}
    if label:
        ev["label"] = {"name": label}
    return ev


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def gh():
    return FakeGitHub()


@pytest.fixture
def tmp_catalog(tmp_path, monkeypatch):
    path = tmp_path / "jobs.yaml"
    path.write_text("version: 1\njobs: []\n", encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    return path


@pytest.fixture
def run_cli(tmp_path, monkeypatch, gh, tmp_catalog):
    """Ejecuta `repo_factory <cmd>` con un evento y un GitHub falso."""
    from repo_factory import cli

    monkeypatch.setattr(cli, "_client", lambda: gh)
    monkeypatch.setenv("GITHUB_REPOSITORY", "ClaroCENAM/claro-repo-factory")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    def run(cmd: str, ev: dict) -> int:
        path = tmp_path / "event.json"
        path.write_text(json.dumps(ev), encoding="utf-8")
        return cli.main([cmd, "--event", str(path)])

    run.output = out
    return run


def b64(text: str) -> dict:
    return {"content": base64.b64encode(text.encode()).decode()}


__all__ = ["FakeGitHub", "GitHubError", "VALID_FIELDS", "b64", "event", "issue_body", "template_files"]
