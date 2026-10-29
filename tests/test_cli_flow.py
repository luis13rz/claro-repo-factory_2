import yaml

from repo_factory import catalog
from tests.conftest import event, issue_body


def comment_text(gh):
    return "\n".join(c["body"] for c in gh.comments)


def test_validar_solicitud_valida(run_cli, gh):
    assert run_cli("validate", event(issue_body(), labels=("solicitud-repo",), action="opened")) == 0
    assert "validada" in gh.labels and "invalida" not in gh.labels
    assert gh.known_labels >= {"solicitud-repo", "validada", "invalida", "aprobado", "creada"}
    text = comment_text(gh)
    assert "✅ Solicitud válida" in text and "job-parque-imei-regional" in text and "`platform-team`" in text


def test_validar_solicitud_con_errores_no_falla_el_workflow(run_cli, gh):
    gh.labels.add("validada")
    assert run_cli("validate", event(issue_body(job_name="Mal Nombre", cluster_size="XXL"), labels=())) == 0
    assert "invalida" in gh.labels and "validada" not in gh.labels
    assert "❌" in comment_text(gh) and "job_name" in comment_text(gh) and "cluster_size" in comment_text(gh)


def test_el_comentario_se_actualiza_no_se_duplica(run_cli, gh):
    run_cli("validate", event(issue_body(job_name="Mal Nombre")))
    run_cli("validate", event(issue_body(), action="edited"))
    assert len(gh.comments) == 1 and "✅" in gh.comments[0]["body"]


def test_editar_despues_de_aprobar_invalida_la_aprobacion(run_cli, gh):
    gh.labels.add("aprobado")
    run_cli("validate", event(issue_body(), action="edited", labels=("solicitud-repo", "aprobado")))
    assert "aprobado" not in gh.labels


def test_validar_detecta_equipo_inexistente_via_api(run_cli, gh):
    gh.teams.pop("oficina-de-datos")
    run_cli("validate", event(issue_body()))
    assert "invalida" in gh.labels and "no existe en ClaroCENAM" in comment_text(gh)


def approve(run_cli, **kw):
    return run_cli("create", event(issue_body(), action="labeled", label="aprobado",
                                   labels=("solicitud-repo", "validada", "aprobado"), **kw))


def test_aprobacion_crea_el_repo_registra_catalogo_y_marca_para_cerrar(run_cli, gh, tmp_catalog):
    gh.labels.add("aprobado")
    assert approve(run_cli, sender="paula", requester="ana") == 0
    assert "job-parque-imei-regional" in gh.repos and "creada" in gh.labels
    entry = catalog.load()[0]
    assert (entry["job_name"], entry["repo"], entry["issue"], entry["requested_by"]) == (
        "parque-imei-regional", "job-parque-imei-regional", 7, "ana")
    assert "created=true" in run_cli.output.read_text()
    assert "✅ Repo creado: https://github.com/ClaroCENAM/job-parque-imei-regional" in comment_text(gh)


def test_cerrar_la_solicitud(run_cli, gh):
    assert run_cli("close", event(issue_body())) == 0 and gh.closed


def test_aprobador_no_autorizado_se_rechaza(run_cli, gh, tmp_catalog):
    gh.labels.add("aprobado")
    assert approve(run_cli, sender="jperez", requester="ana") == 0
    assert "aprobado" not in gh.labels and not any(r.startswith("job-") for r in gh.repos)
    assert "no pertenece a un equipo aprobador" in comment_text(gh) and catalog.load() == []
    assert "created=true" not in (run_cli.output.read_text() if run_cli.output.exists() else "")


def test_nadie_aprueba_su_propia_solicitud(run_cli, gh):
    gh.labels.add("aprobado")
    approve(run_cli, sender="paula", requester="paula")
    assert "propia solicitud" in comment_text(gh) and "aprobado" not in gh.labels and "job-parque-imei-regional" not in gh.repos


def test_sin_validacion_previa_no_se_crea(run_cli, gh):
    gh.labels.add("aprobado")
    run_cli("create", event(issue_body(), action="labeled", label="aprobado", labels=("solicitud-repo", "aprobado")))
    assert "no está validada" in comment_text(gh) and "job-parque-imei-regional" not in gh.repos


def test_se_revalida_con_el_contenido_actual(run_cli, gh):
    gh.labels.add("aprobado")
    run_cli("create", event(issue_body(cluster_size="XXL"), action="labeled", label="aprobado",
                            labels=("solicitud-repo", "validada", "aprobado")))
    assert "ya no es válida" in comment_text(gh) and "job-parque-imei-regional" not in gh.repos


def test_falla_de_creacion_se_reporta_y_permite_reintentar(run_cli, gh, tmp_catalog):
    gh.labels.add("aprobado")
    gh.teams.pop("platform-team")  # primero falla el preflight de configuración
    approve(run_cli, sender="ana", requester="x")  # 'ana' sigue siendo aprobadora; se rechaza por preflight
    assert "ya no es válida" in comment_text(gh) and catalog.load() == []
    gh.teams["platform-team"] = {"id": 1}
    gh.labels.add("aprobado")
    assert approve(run_cli, sender="paula", requester="ana") == 0 and "job-parque-imei-regional" in gh.repos


def test_reaprobar_tras_un_fallo_parcial_completa_sin_duplicar(run_cli, gh, tmp_catalog, monkeypatch):
    from repo_factory import provision as prov

    gh.labels.add("aprobado")
    original = gh.protect_branch

    def boom(*a, **k):
        raise prov.GitHubError("PUT", "/protection", 403, "plan no soporta protección en repos privados")

    monkeypatch.setattr(gh, "protect_branch", boom)
    assert approve(run_cli, sender="paula", requester="ana") == 1
    assert "❌ **Proteger ramas**" in comment_text(gh) and "plan no soporta" in comment_text(gh)
    assert "aprobado" not in gh.labels and catalog.load() == []
    commits = len(gh.commits)

    monkeypatch.setattr(gh, "protect_branch", original)
    gh.labels.add("aprobado")
    assert approve(run_cli, sender="paula", requester="ana") == 0
    assert len(gh.commits) == commits and gh.calls.count("generate") == 1 and len(catalog.load()) == 1
    assert set(gh.repos["job-parque-imei-regional"]["protection"]) == {"dev", "prod"}


def test_catalogo_serializado_es_yaml_valido(run_cli, gh, tmp_catalog):
    gh.labels.add("aprobado")
    approve(run_cli, sender="paula", requester="ana")
    assert yaml.safe_load(tmp_catalog.read_text())["jobs"][0]["tech_lead"] == "jperez"
