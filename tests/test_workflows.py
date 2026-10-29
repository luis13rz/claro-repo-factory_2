"""Garantías estáticas de los workflows: entradas no confiables, permisos y ejecución serializada."""
from pathlib import Path

import yaml

WF = Path(".github/workflows")
LOAD = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in WF.glob("*.yml")}
TEXT = {p.name: p.read_text(encoding="utf-8") for p in WF.glob("*.yml")}


def runs(doc):
    return [str(st.get("run", "")) for job in doc["jobs"].values() for st in job.get("steps", [])]


def test_el_contenido_del_issue_nunca_se_interpola_en_comandos():
    for name, doc in LOAD.items():
        for cmd in runs(doc):
            for risky in ("github.event.issue.title", "github.event.issue.body", "github.event.comment",
                          "github.head_ref", "github.event.issue.user"):
                assert risky not in cmd, f"{name}: {risky} dentro de un run"


def test_no_hay_pull_request_target_ni_secretos_de_usuario():
    for text in TEXT.values():
        assert "pull_request_target" not in text
    assert "secrets.GITHUB_TOKEN" not in "".join(TEXT.values())


def test_crear_solo_con_la_etiqueta_aprobado_y_en_serie():
    job = LOAD["create-repo.yml"]["jobs"]["create"]
    assert "github.event.label.name == 'aprobado'" in job["if"] and "solicitud-repo" in job["if"]
    assert LOAD["create-repo.yml"]["concurrency"]["cancel-in-progress"] is False
    assert job["environment"] == "repo-factory"


def test_validar_no_crea_nada_y_corre_con_el_environment_restringido():
    doc = LOAD["validate-request.yml"]
    assert "create" not in "".join(runs(doc)).replace("create-github-app-token", "")
    assert doc["jobs"]["validate"]["environment"] == "repo-factory"
    assert doc["permissions"] == {"contents": "read"}


def test_los_pasos_posteriores_solo_corren_si_se_creo_el_repo():
    steps = LOAD["create-repo.yml"]["jobs"]["create"]["steps"]
    by_name = {s.get("name"): s for s in steps}
    for name in ("Registrar en el catálogo", "Cerrar la solicitud"):
        assert by_name[name]["if"] == "steps.create.outputs.created == 'true'"
