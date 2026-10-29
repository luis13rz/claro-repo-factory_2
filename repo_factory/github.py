"""Cliente mínimo de la API de GitHub (solo biblioteca estándar). El transporte es inyectable para las pruebas."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable

API = "https://api.github.com"
Transport = Callable[[str, str, dict | None], tuple[int, object]]


class GitHubError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: object):
        super().__init__(f"{method} {path} -> {status}: {str(body)[:300]}")
        self.status, self.body = status, body


def urllib_transport(token: str) -> Transport:
    def send(method: str, path: str, payload: dict | None) -> tuple[int, object]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "claro-repo-factory",
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  (URL fija a api.github.com)
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else None
            except ValueError:
                return e.code, raw.decode(errors="replace")
    return send


class GitHubClient:
    def __init__(self, transport: Transport, *, sleep: Callable[[float], None] = time.sleep):
        self._send, self._sleep = transport, sleep

    # --- base
    def _call(self, method: str, path: str, payload: dict | None = None, *, ok: tuple[int, ...] = (200, 201, 204),
              missing_ok: bool = False) -> object:
        for attempt in range(3):  # reintento ante errores transitorios del servidor
            status, body = self._send(method, path, payload)
            if status in (502, 503, 504) and attempt < 2:
                self._sleep(2 ** attempt)
                continue
            break
        if status in ok:
            return body
        if status == 404 and missing_ok:
            return None
        raise GitHubError(method, path, status, body)

    # --- repos
    def get_repo(self, owner: str, repo: str) -> dict | None:
        return self._call("GET", f"/repos/{owner}/{repo}", missing_ok=True)  # type: ignore[return-value]

    def generate_from_template(self, template_owner: str, template_repo: str, owner: str, name: str,
                               description: str) -> dict:
        return self._call("POST", f"/repos/{template_owner}/{template_repo}/generate", {
            "owner": owner, "name": name, "description": description, "private": True,
            "include_all_branches": False})  # type: ignore[return-value]

    def get_topics(self, owner: str, repo: str) -> list[str]:
        body = self._call("GET", f"/repos/{owner}/{repo}/topics")
        return list(body.get("names", []))  # type: ignore[union-attr]

    def set_topics(self, owner: str, repo: str, topics: list[str]) -> None:
        self._call("PUT", f"/repos/{owner}/{repo}/topics", {"names": topics})

    # --- contenido
    def get_file(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        body = self._call("GET", f"/repos/{owner}/{repo}/contents/{path}?ref={ref}", missing_ok=True)
        if body is None:
            return None
        return base64.b64decode(body["content"]).decode("utf-8")  # type: ignore[index]

    def branch_sha(self, owner: str, repo: str, branch: str) -> str | None:
        body = self._call("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", missing_ok=True)
        return None if body is None else body["object"]["sha"]  # type: ignore[index]

    def commit_files(self, owner: str, repo: str, branch: str, message: str, files: dict[str, str]) -> str:
        """Un solo commit con todos los archivos (evita disparar el pipeline varias veces)."""
        head = self.branch_sha(owner, repo, branch)
        if head is None:
            raise GitHubError("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", 404, "rama inexistente")
        commit = self._call("GET", f"/repos/{owner}/{repo}/git/commits/{head}")
        tree = self._call("POST", f"/repos/{owner}/{repo}/git/trees", {
            "base_tree": commit["tree"]["sha"],  # type: ignore[index]
            "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in sorted(files.items())]})
        new = self._call("POST", f"/repos/{owner}/{repo}/git/commits", {
            "message": message, "tree": tree["sha"], "parents": [head]})  # type: ignore[index]
        self._call("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", {"sha": new["sha"], "force": False})  # type: ignore[index]
        return new["sha"]  # type: ignore[index]

    def create_branch(self, owner: str, repo: str, name: str, sha: str) -> None:
        self._call("POST", f"/repos/{owner}/{repo}/git/refs", {"ref": f"refs/heads/{name}", "sha": sha})

    # --- seguridad del repo
    def put_environment(self, owner: str, repo: str, name: str, *, reviewer_team_ids: list[int], branch: str) -> None:
        body: dict = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
        if reviewer_team_ids:
            body["reviewers"] = [{"type": "Team", "id": i} for i in reviewer_team_ids]
        self._call("PUT", f"/repos/{owner}/{repo}/environments/{name}", body)
        # 422 = la política de esa rama ya existe (reintento)
        self._call("POST", f"/repos/{owner}/{repo}/environments/{name}/deployment-branch-policies",
                   {"name": branch, "type": "branch"}, ok=(200, 201, 422))

    def protect_branch(self, owner: str, repo: str, branch: str, *, checks: list[str], approvals: int) -> None:
        self._call("PUT", f"/repos/{owner}/{repo}/branches/{branch}/protection", {
            "required_status_checks": {"strict": True, "contexts": checks},
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "required_approving_review_count": approvals, "require_code_owner_reviews": True,
                "dismiss_stale_reviews": True},
            "restrictions": None, "allow_force_pushes": False, "allow_deletions": False,
            "required_conversation_resolution": True})

    # --- equipos y usuarios
    def get_team(self, org: str, slug: str) -> dict | None:
        return self._call("GET", f"/orgs/{org}/teams/{slug}", missing_ok=True)  # type: ignore[return-value]

    def is_team_member(self, org: str, slug: str, user: str) -> bool:
        body = self._call("GET", f"/orgs/{org}/teams/{slug}/memberships/{user}", missing_ok=True)
        return bool(body) and body.get("state") == "active"  # type: ignore[union-attr]

    def user_exists(self, login: str) -> bool:
        return self._call("GET", f"/users/{login}", missing_ok=True) is not None

    def add_team_repo(self, org: str, slug: str, owner: str, repo: str, permission: str) -> None:
        self._call("PUT", f"/orgs/{org}/teams/{slug}/repos/{owner}/{repo}", {"permission": permission})

    # --- issues
    def list_comments(self, repo: str, number: int) -> list[dict]:
        return self._call("GET", f"/repos/{repo}/issues/{number}/comments?per_page=100")  # type: ignore[return-value]

    def create_comment(self, repo: str, number: int, body: str) -> None:
        self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})

    def update_comment(self, repo: str, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})

    def ensure_label(self, repo: str, name: str, color: str, description: str) -> None:
        self._call("POST", f"/repos/{repo}/labels", {"name": name, "color": color, "description": description},
                   ok=(200, 201, 422))  # 422 = ya existe

    def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        self._call("POST", f"/repos/{repo}/issues/{number}/labels", {"labels": labels})

    def remove_label(self, repo: str, number: int, label: str) -> None:
        self._call("DELETE", f"/repos/{repo}/issues/{number}/labels/{label}", ok=(200, 204, 404))

    def close_issue(self, repo: str, number: int) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/{number}", {"state": "closed", "state_reason": "completed"})
