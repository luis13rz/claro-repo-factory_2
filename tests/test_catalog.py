import pytest

from repo_factory import catalog

E = {"job_name": "a-job", "repo": "job-a-job", "owner_team": "eq", "cost_center": "CC-1", "tech_lead": "x",
     "requested_by": "y", "issue": 1, "created_at": "2026-01-01T00:00:00Z"}


def test_catalogo_real_es_valido():
    assert catalog.load() == []


def test_agregar_ordenar_y_reintento_idempotente(tmp_catalog):
    assert catalog.add({**E, "job_name": "z-job", "repo": "job-z-job"}) is True
    assert catalog.add(E) is True
    assert [e["job_name"] for e in catalog.load()] == ["a-job", "z-job"]
    assert catalog.add(E) is False  # mismo contenido: no hace nada


def test_entrada_distinta_para_el_mismo_job_falla(tmp_catalog):
    catalog.add(E)
    with pytest.raises(catalog.CatalogError, match="distinta"):
        catalog.add({**E, "issue": 99})


def test_catalogo_invalido(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("version: 2\njobs: []\n")
    with pytest.raises(catalog.CatalogError):
        catalog.load(p)
    p.write_text("version: 1\njobs: [{job_name: a}]\n")
    with pytest.raises(catalog.CatalogError, match="exactamente"):
        catalog.load(p)
    p.write_text("version: 1\njobs: [{job_name: a, repo: r}, {job_name: a, repo: r}]\n")
    with pytest.raises(catalog.CatalogError, match="duplicados"):
        catalog.load(p)
