import importlib.util

import pytest
import yaml

from repo_factory.customize import MARKER, build_codeowners, customize_all
from repo_factory.request import JobRequest
from tests.conftest import template_files

REQ = JobRequest("parque-imei", "oficina-de-datos", "CC-1", "Cierre mensual del parque IMEI", "L", "previous_month",
                 "0 0 6 1 * ?", ("a@claro.com.gt", "b@claro.com.gt"), "jperez", 7, "ana")


def sources():
    t = template_files()
    return {k: t[k] for k in ("job.config.yaml", "databricks.yml", "README.md")}


def test_datos_del_formulario_en_job_config(cfg):
    out = customize_all(sources(), REQ, cfg)
    job = yaml.safe_load(out["job.config.yaml"])["job"]
    assert (job["name"], job["owner_team"], job["cost_center"], job["period_mode"]) == (
        "parque-imei", "oficina-de-datos", "CC-1", "previous_month")
    assert job["cluster"]["size"] == "L" and job["schedule"]["cron"] == "0 0 6 1 * ?"
    assert job["notifications"]["on_failure"] == ["a@claro.com.gt", "b@claro.com.gt"]


def test_se_quitan_los_ejemplos_que_romperian_el_primer_despliegue(cfg):
    job = yaml.safe_load(customize_all(sources(), REQ, cfg)["job.config.yaml"])["job"]
    for sample in ("permissions", "parameters", "quality_gate"):
        assert sample not in job


def test_sin_schedule_se_elimina_el_bloque(cfg):
    job = yaml.safe_load(customize_all(sources(), JobRequest(**{**REQ.__dict__, "schedule_cron": None}), cfg)
                         ["job.config.yaml"])["job"]
    assert "schedule" not in job


def test_se_conservan_los_comentarios_de_la_plantilla(cfg):
    assert "# Única fuente de verdad del job" in customize_all(sources(), REQ, cfg)["job.config.yaml"]


def test_bundle_nombre_y_ruta_de_despliegue(cfg):
    doc = yaml.safe_load(customize_all(sources(), REQ, cfg)["databricks.yml"])
    assert doc["bundle"]["name"] == "parque-imei"
    for target in doc["targets"].values():
        assert target["workspace"]["root_path"] == "/Workspace/Shared/jobs/oficina-de-datos/parque-imei/${bundle.target}"
    assert doc["targets"]["prod"]["mode"] == "production" and "run_as" in doc


def test_codeowners(cfg):
    text = build_codeowners(REQ, cfg)
    assert "/.github/         @ClaroCENAM/platform-team" in text
    assert "/src/             @ClaroCENAM/oficina-de-datos @jperez" in text


def test_readme_con_datos_y_marcador(cfg):
    readme = customize_all(sources(), REQ, cfg)["README.md"]
    assert readme.startswith("# parque-imei") and MARKER in readme and "@jperez" in readme and "#7" in readme
    assert "# <nombre-del-job>" not in readme


def test_es_idempotente(cfg):
    once = customize_all(sources(), REQ, cfg)
    again = customize_all({k: once[k] for k in sources()}, REQ, cfg)
    assert again == once


@pytest.mark.skipif(importlib.util.find_spec("platform_ci") is None, reason="platform-ci no instalado")
def test_el_repo_generado_pasa_el_validador_del_repo_de_plataforma(cfg, tmp_path, monkeypatch):
    """Verificación cruzada: lo que fabrica este servicio es aceptado por el pipeline de plataforma."""
    from platform_ci.cli import main as platform_main

    for path, content in customize_all(sources(), REQ, cfg).items():
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    nb = tmp_path / "src" / "notebooks" / "main.py"
    nb.parent.mkdir(parents=True)
    nb.write_text("# Databricks notebook source\nx = 1\n", encoding="utf-8")
    monkeypatch.setenv("PLATFORM_ALLOWED_EMAIL_DOMAINS", "claro.com.gt")
    assert platform_main(["validate-config", "--repo-root", str(tmp_path)]) == 0
