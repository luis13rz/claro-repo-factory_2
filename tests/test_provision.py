import pytest

from repo_factory.provision import ProvisionError, marker_topic, preflight, provision, succeeded
from repo_factory.request import JobRequest
from tests.conftest import FakeGitHub

REQ = JobRequest("parque-imei", "oficina-de-datos", "CC-1", "Cierre mensual del parque IMEI", "L", "previous_month",
                 "0 0 6 1 * ?", ("a@claro.com.gt",), "jperez", 7, "ana")
REPO = "job-parque-imei"


def test_creacion_completa(cfg, gh):
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    assert succeeded(steps) and [s.name for s in steps] == [
        "Crear repo desde la plantilla", "Esperar el contenido", "Personalizar archivos", "Crear ramas de ambiente",
        "Asignar equipos", "Configurar Environments", "Proteger ramas"]
    r = gh.repos[REPO]
    assert r["topics"] == ["databricks-job", marker_topic(7)] and r["description"] == REQ.description
    # un solo commit, sin disparar el pipeline todavía
    assert len(gh.commits) == 1 and gh.commits[0]["message"].endswith("[skip ci]")
    assert gh.commits[0]["files"] == [".github/CODEOWNERS", "README.md", "databricks.yml", "job.config.yaml"]
    assert set(r["branches"]) == {"dev", "prod"}
    # solo prod exige aprobación; cada environment solo despliega desde su rama
    assert r["envs"] == {"dev": {"reviewers": [], "branch": "dev"}, "prod": {"reviewers": [1], "branch": "prod"}}
    assert set(r["protection"]) == {"dev", "prod"}
    assert r["protection"]["prod"] == {"checks": ["pipeline / quality"], "approvals": 1}
    assert r["perms"] == {"oficina-de-datos": "push", "platform-team": "admin"}


def test_la_proteccion_se_aplica_despues_del_commit_de_personalizacion(cfg, gh):
    """Con enforce_admins el commit directo ya no sería posible: el orden importa."""
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    names = [s.name for s in steps]
    assert names.index("Personalizar archivos") < names.index("Proteger ramas")


def test_los_equipos_tienen_acceso_antes_de_ser_revisores_de_un_environment(cfg, gh):
    names = [s.name for s in provision(REQ, cfg, gh, sleep=lambda s: None)]
    assert names.index("Asignar equipos") < names.index("Configurar Environments")


def test_reintento_no_duplica_nada(cfg, gh):
    provision(REQ, cfg, gh, sleep=lambda s: None)
    before = (len(gh.commits), dict(gh.repos[REPO]["branches"]))
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    assert succeeded(steps) and "reintento" in steps[0].detail and "sin cambios" in steps[2].detail
    assert (len(gh.commits), gh.repos[REPO]["branches"]) == before and gh.calls.count("generate") == 1


def test_repo_existente_de_otra_solicitud_no_se_toca(cfg, gh):
    gh.repos[REPO] = {"is_template": False, "topics": ["otra-cosa"]}
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    assert len(steps) == 1 and not steps[0].ok and "no fue creado por la solicitud #7" in steps[0].detail
    assert gh.commits == []


def test_espera_a_que_la_plantilla_termine_de_generarse(cfg):
    gh, sleeps = FakeGitHub(ready_after=3), []
    assert succeeded(provision(REQ, cfg, gh, sleep=sleeps.append)) and len(sleeps) == 3


def test_plantilla_que_nunca_termina_falla_con_mensaje_claro(cfg):
    gh = FakeGitHub(ready_after=10_000)
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    assert not steps[-1].ok and steps[-1].name == "Esperar el contenido" and "reintenta" in steps[-1].detail


def test_si_un_paso_falla_se_detiene_y_no_continua(cfg, gh):
    del gh.teams["platform-team"]  # el equipo revisor no existe
    steps = provision(REQ, cfg, gh, sleep=lambda s: None)
    assert steps[-1].name == "Configurar Environments" and not steps[-1].ok
    assert "Proteger ramas" not in [s.name for s in steps] and gh.repos[REPO]["protection"] == {}


# ---- preflight
def test_preflight_ok(cfg, gh):
    assert preflight(REQ, cfg, gh) == []


@pytest.mark.parametrize("mutate,field", [
    (lambda g: g.teams.pop("oficina-de-datos"), "owner_team"),
    (lambda g: g.users.discard("jperez"), "tech_lead"),
    (lambda g: g.members.discard(("oficina-de-datos", "jperez")), "tech_lead"),
    (lambda g: g.repos.update({REPO: {"topics": []}}), "job_name"),
    (lambda g: g.repos["template-databricks-job"].update(is_template=False), "configuración"),
    (lambda g: g.teams.pop("platform-team"), "configuración"),
])
def test_preflight_detecta(cfg, gh, mutate, field):
    mutate(gh)
    assert field in {p.field for p in preflight(REQ, cfg, gh)}


def test_preflight_permite_reintentar_el_repo_de_la_misma_solicitud(cfg, gh):
    gh.repos[REPO] = {"topics": [marker_topic(7)]}
    assert preflight(REQ, cfg, gh) == []


def test_error_de_provision_tiene_tipo_propio():
    assert issubclass(ProvisionError, RuntimeError)
