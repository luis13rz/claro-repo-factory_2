from pathlib import Path

import pytest

from repo_factory.config import ConfigError, load_config
from repo_factory.request import parse_issue_body
from repo_factory.validation import validate_request
from tests.conftest import issue_body


def check(cfg, jobs=frozenset(), repos=frozenset(), **overrides):
    return validate_request(parse_issue_body(issue_body(**overrides)), cfg, issue_number=7, requester="ana",
                            existing_jobs=jobs, existing_repos=repos)


def fields(problems):
    return {p.field for p in problems}


def test_solicitud_valida(cfg):
    req, problems = check(cfg)
    assert problems == [] and req.job_name == "parque-imei-regional" and req.tech_lead == "jperez"
    assert req.alert_emails == ("datos-alertas@claro.com.gt",) and cfg.repo_name(req.job_name) == "job-parque-imei-regional"


def test_sin_schedule_es_valido(cfg):
    req, problems = check(cfg, schedule_cron="")
    assert problems == [] and req.schedule_cron is None


@pytest.mark.parametrize("name", ["Parque-IMEI", "parque_imei", "-parque", "parque-", "parque--imei", "1parque",
                                  "ab", "x" * 51, "parque imei", "parque/imei", "parque\ndos"])
def test_nombres_invalidos(cfg, name):
    assert "job_name" in fields(check(cfg, job_name=name)[1])


@pytest.mark.parametrize("name", ["template", "demo", "prueba"])
def test_nombres_reservados(cfg, name):
    assert "reservado" in check(cfg, job_name=name)[1][0].message


def test_duplicados_contra_el_catalogo(cfg):
    assert "ya existe un job" in check(cfg, jobs={"parque-imei-regional"})[1][0].message
    assert "ya existe el repo" in check(cfg, repos={"job-parque-imei-regional"})[1][0].message


@pytest.mark.parametrize("field,value", [
    ("owner_team", "Equipo Datos"), ("cost_center", "CC 1"), ("description", "corta"), ("description", "x" * 501),
    ("description", "línea uno válida\nlínea dos"), ("cluster_size", "XXL"), ("period_mode", "weekly"),
    ("schedule_cron", "0 0 6 1 * *"), ("schedule_cron", "cada mes"), ("tech_lead", "pe rez"),
    ("tech_lead", "-perez"), ("alert_emails", "persona@gmail.com"), ("alert_emails", "no-es-correo"),
    ("alert_emails", "a@claro.com.gt, a@claro.com.gt"), ("confirmations", "- [x] a\n- [ ] b\n- [x] c"),
])
def test_campos_invalidos(cfg, field, value):
    assert field in fields(check(cfg, **{field: value})[1])


def test_demasiados_correos(cfg):
    many = ", ".join(f"l{i}@claro.com.gt" for i in range(6))
    assert "alert_emails" in fields(check(cfg, alert_emails=many)[1])


def test_varios_correos_validos(cfg):
    req, problems = check(cfg, alert_emails="a@claro.com.gt, b@claro.com.gt")
    assert problems == [] and len(req.alert_emails) == 2


def test_obligatorios_vacios_se_reportan_todos(cfg):
    _, problems = check(cfg, job_name="", cost_center="", tech_lead="")
    assert {"job_name", "cost_center", "tech_lead"} <= fields(problems)


def test_formulario_alterado_se_rechaza(cfg):
    body = issue_body().replace("### Talla de cluster", "### Talla")
    req, problems = validate_request(parse_issue_body(body), cfg, issue_number=1, requester="x")
    assert req is None and problems[0].field == "formulario" and "Talla de cluster" in problems[0].message


def test_arroba_en_responsable_se_acepta(cfg):
    assert check(cfg, tech_lead="@jperez")[0].tech_lead == "jperez"


# ---- configuración
def test_config_por_defecto(cfg):
    assert cfg.repo_prefix == "job-" and cfg.default_branch == "dev" and "prod" in cfg.approval_environments


@pytest.mark.parametrize("edit,msg", [
    (lambda d: d.pop("org"), "faltan"), (lambda d: d.update(extra=1), "sobran"),
    (lambda d: d.update(default_branch="main"), "default_branch"),
    (lambda d: d.update(branches=["Dev", "prod"], default_branch="Dev"), "minúsculas"),
    (lambda d: d.update(approval_environments=["qa"]), "subconjunto"),
    (lambda d: d.update(workspace_root="/tmp/x"), "/Workspace/"),
    (lambda d: d.update(required_approvals=0), "entero"), (lambda d: d.update(forbid_self_approval="si"), "true/false"),
    (lambda d: d.update(approver_teams=[]), "no vacía"),
])
def test_config_invalida(tmp_path, edit, msg):
    import yaml

    data = yaml.safe_load(Path("factory.yaml").read_text(encoding="utf-8"))
    edit(data)
    path = tmp_path / "f.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match=msg):
        load_config(path)
