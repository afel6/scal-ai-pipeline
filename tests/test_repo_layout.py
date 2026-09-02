"""D1 — structural blockers for the move to another machine.

1. scal's package is `hviel`, not `src`: both hub apps own a top-level package,
   and two `src` packages cannot import in one process (no in-process bridge
   test, and A2A later).
2. Every store path is explicit and anchored to the repo, never to the CWD:
   `PRCReportEngine` read a CWD-relative `chat_history.db` while the app wrote
   `DB_DIR/chat_history.db` — two databases depending on where you launched.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_scal_package_is_hviel_not_src():
    import hviel.rag.router
    import hviel.rakeza.contracts
    import hviel.utils.units
    assert pathlib.Path(hviel.rag.router.__file__).parent.parent.name == "hviel"
    assert not (ROOT / "src").exists()


def test_store_paths_are_absolute_and_repo_anchored():
    import app
    import config
    for p in (app.DB_PATH, config.settings.DB_DIR, config.settings.CHROMA_DIR,
              config.settings.graph_db_path):
        assert pathlib.Path(p).is_absolute(), p


def test_report_engine_reads_the_database_the_app_writes(monkeypatch, tmp_path):
    import app
    import report_generator
    monkeypatch.chdir(tmp_path)                          # launched from anywhere
    assert report_generator.PRCReportEngine().db_path == app.DB_PATH
    assert pathlib.Path(app.DB_PATH).is_absolute()


def test_vector_store_default_is_repo_anchored(monkeypatch, tmp_path):
    import config
    import rag_database
    monkeypatch.chdir(tmp_path)
    p = pathlib.Path(rag_database.default_persist_dir())
    assert p.is_absolute() and p == pathlib.Path(config.settings.CHROMA_DIR)


def test_log_dir_default_is_repo_anchored(monkeypatch, tmp_path):
    import logger_setup
    monkeypatch.delenv("LOG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    p = pathlib.Path(logger_setup.default_log_dir())
    assert p.is_absolute() and p == ROOT / "logs"
