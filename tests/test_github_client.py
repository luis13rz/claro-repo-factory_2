import base64

import pytest

from repo_factory.github import GitHubClient, GitHubError


class Recorder:
    def __init__(self, *responses):
        self.calls, self.responses = [], list(responses)

    def __call__(self, method, path, payload):
        self.calls.append((method, path, payload))
        return self.responses.pop(0) if self.responses else (200, {})


def client(*responses, sleeps=None):
    rec = Recorder(*responses)
    return GitHubClient(rec, sleep=(sleeps.append if sleeps is not None else (lambda s: None))), rec


def test_generar_desde_plantilla_crea_repo_privado_sin_todas_las_ramas():
    gh, rec = client((201, {"name": "job-x"}))
    gh.generate_from_template("O", "tpl", "O", "job-x", "desc")
    method, path, body = rec.calls[0]
    assert (method, path) == ("POST", "/repos/O/tpl/generate")
    assert body == {"owner": "O", "name": "job-x", "description": "desc", "private": True, "include_all_branches": False}


def test_404_devuelve_none_solo_si_se_permite():
    gh, _ = client((404, {}), (404, {}))
    assert gh.get_repo("O", "x") is None
    with pytest.raises(GitHubError) as e:
        gh.get_topics("O", "x")
    assert e.value.status == 404


def test_commit_unico_con_git_data_api():
    gh, rec = client((200, {"object": {"sha": "H"}}), (200, {"tree": {"sha": "T0"}}), (201, {"sha": "T1"}),
                     (201, {"sha": "C1"}), (200, {}))
    assert gh.commit_files("O", "r", "dev", "msg [skip ci]", {"b.txt": "2", "a.txt": "1"}) == "C1"
    (_, p1, _), (_, p2, _), (_, p3, tree), (_, p4, commit), (m5, p5, ref) = rec.calls
    assert p1.endswith("/git/ref/heads/dev") and p2.endswith("/git/commits/H") and p3.endswith("/git/trees")
    assert tree["base_tree"] == "T0" and [e["path"] for e in tree["tree"]] == ["a.txt", "b.txt"]
    assert commit == {"message": "msg [skip ci]", "tree": "T1", "parents": ["H"]}
    assert (m5, p5, ref) == ("PATCH", "/repos/O/r/git/refs/heads/dev", {"sha": "C1", "force": False})


def test_commit_en_rama_inexistente_falla():
    gh, _ = client((404, {}))
    with pytest.raises(GitHubError, match="rama inexistente"):
        gh.commit_files("O", "r", "nope", "m", {"a": "b"})


def test_leer_archivo_decodifica_base64():
    gh, rec = client((200, {"content": base64.b64encode("hola ñ".encode()).decode()}))
    assert gh.get_file("O", "r", "a.txt", "dev") == "hola ñ"
    assert rec.calls[0][1] == "/repos/O/r/contents/a.txt?ref=dev"


def test_environment_con_revisores_y_rama_restringida():
    gh, rec = client((200, {}), (201, {}))
    gh.put_environment("O", "r", "prod", reviewer_team_ids=[1, 2], branch="prod")
    (m1, p1, b1), (m2, p2, b2) = rec.calls
    assert (m1, p1) == ("PUT", "/repos/O/r/environments/prod")
    assert b1["reviewers"] == [{"type": "Team", "id": 1}, {"type": "Team", "id": 2}]
    assert b1["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}
    assert (m2, p2, b2) == ("POST", "/repos/O/r/environments/prod/deployment-branch-policies",
                            {"name": "prod", "type": "branch"})


def test_environment_sin_revisores_y_politica_ya_existente():
    gh, rec = client((200, {}), (422, {"message": "already exists"}))
    gh.put_environment("O", "r", "dev", reviewer_team_ids=[], branch="dev")  # 422 se tolera (reintento)
    assert "reviewers" not in rec.calls[0][2]


def test_proteccion_de_rama():
    gh, rec = client((200, {}))
    gh.protect_branch("O", "r", "prod", checks=["pipeline / quality"], approvals=1)
    body = rec.calls[0][2]
    assert rec.calls[0][:2] == ("PUT", "/repos/O/r/branches/prod/protection")
    assert body["enforce_admins"] is True and body["allow_force_pushes"] is False and body["allow_deletions"] is False
    assert body["required_status_checks"] == {"strict": True, "contexts": ["pipeline / quality"]}
    assert body["required_pull_request_reviews"]["require_code_owner_reviews"] is True


def test_membresia_de_equipo():
    gh, _ = client((200, {"state": "active"}), (200, {"state": "pending"}), (404, {}))
    assert gh.is_team_member("O", "t", "u") is True
    assert gh.is_team_member("O", "t", "u") is False
    assert gh.is_team_member("O", "t", "u") is False


def test_reintenta_errores_transitorios():
    sleeps = []
    gh, rec = client((503, {}), (502, {}), (200, {"name": "x"}), sleeps=sleeps)
    assert gh.get_repo("O", "x") == {"name": "x"} and len(rec.calls) == 3 and sleeps == [1, 2]


def test_error_persistente_se_propaga():
    gh, _ = client((503, {}), (503, {}), (503, {}))
    with pytest.raises(GitHubError, match="503"):
        gh.get_repo("O", "x")


def test_etiqueta_existente_no_es_error():
    gh, _ = client((422, {"message": "already_exists"}))
    gh.ensure_label("O/r", "validada", "0075CA", "d")
