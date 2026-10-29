from pathlib import Path

import yaml

from repo_factory.request import LABELS, OPTIONAL, confirmations_ok, parse_issue_body
from tests.conftest import issue_body

FORM = yaml.safe_load(Path(".github/ISSUE_TEMPLATE/solicitud-repo-job.yml").read_text(encoding="utf-8"))
FIELDS = [b for b in FORM["body"] if b["type"] != "markdown"]


def test_parse_cuerpo_completo():
    raw = parse_issue_body(issue_body())
    assert raw.fields["job_name"] == "parque-imei-regional" and raw.missing == [] and raw.unknown == []


def test_campo_opcional_vacio_es_cadena_vacia():
    assert parse_issue_body(issue_body(schedule_cron="")).fields["schedule_cron"] == ""


def test_secciones_faltantes_y_desconocidas():
    body = issue_body().replace("### Centro de costo", "### Otra cosa")
    raw = parse_issue_body(body)
    assert raw.missing == ["Centro de costo"] and raw.unknown == ["Otra cosa"]


def test_cuerpo_vacio_o_nulo():
    assert len(parse_issue_body(None).missing) == len(LABELS) and parse_issue_body("").fields == {}


def test_confirmaciones():
    assert confirmations_ok("- [x] a\n- [X] b\n- [x] c")
    assert not confirmations_ok("- [x] a\n- [ ] b\n- [x] c")
    assert not confirmations_ok("- [x] a\n- [x] b")


def test_el_formulario_y_el_parser_usan_las_mismas_etiquetas():
    """Si alguien renombra una etiqueta del formulario sin actualizar el parser, este test lo detecta."""
    assert [f["attributes"]["label"] for f in FIELDS] == list(LABELS)
    assert [f["id"] for f in FIELDS] == list(LABELS.values())


def test_el_formulario_exige_todo_menos_el_schedule():
    for f in FIELDS:
        needs = f["id"] not in OPTIONAL
        required = f.get("validations", {}).get("required", False) or f["type"] == "checkboxes"
        assert required == needs, f["id"]


def test_opciones_del_formulario_coinciden_con_factory_yaml(cfg):
    by_id = {f["id"]: f for f in FIELDS}
    assert tuple(by_id["cluster_size"]["attributes"]["options"]) == cfg.cluster_sizes
    assert tuple(by_id["period_mode"]["attributes"]["options"]) == cfg.period_modes
    assert len(by_id["confirmations"]["attributes"]["options"]) == 3
    assert FORM["labels"] == ["solicitud-repo"]
