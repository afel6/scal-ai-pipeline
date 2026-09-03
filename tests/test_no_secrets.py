"""D3 0.4 — no tracked file may carry credential material.

CI runs gitleaks over the whole history (a finding fails the build); this test
is the local, offline half: every file git tracks is scanned for the shapes
this project has actually leaked or held — Gemini keys, NVIDIA NIM keys, Neon
passwords, Postgres URLs with a real password, private keys. Placeholders from
.env.example are allowed by exact shape only.
"""
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATTERNS = {
    "google-api-key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "nvidia-nim-key": re.compile(r"nvapi-[0-9A-Za-z_\-]{20,}"),
    "neon-password": re.compile(r"npg_[0-9A-Za-z]{10,}"),
    "postgres-url-with-password": re.compile(r"postgres(?:ql)?://[A-Za-z0-9_.\-]+:([^@\s'\"$*<{]+)@[A-Za-z0-9.\-]+"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
}
PLACEHOLDER_PASSWORDS = {"password", "PASSWORD", "postgres", "changeme", "NEW_PASSWORD"}
SKIP_SUFFIXES = {".png", ".jpg", ".pdf", ".xls", ".xlsx", ".db", ".sqlite", ".ico", ".docx", ".pptx", ".bin"}
SKIP_PARTS = {"hermes_skills_library", "node_modules", ".venv"}


def _tracked_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout
    return [ROOT / p for p in out.splitlines() if p and not set(pathlib.Path(p).parts) & SKIP_PARTS
            and pathlib.Path(p).suffix.lower() not in SKIP_SUFFIXES and p != ".gitleaks.toml"]


def findings_in(text: str):
    hits = []
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            if name == "postgres-url-with-password":
                pw = m.group(1)
                if pw in PLACEHOLDER_PASSWORDS or pw.startswith("change_this") or pw.startswith("your_") or set(pw) == {"*"}:
                    continue
            hits.append((name, m.group(0)[:6] + "…"))         # never the value
    return hits


def test_scanner_catches_the_shapes_this_project_leaked():
    sample = ("GEMINI_API_KEY=AIzaSyD" + "x" * 33 + "\nDATABASE_URL=postgresql://neondb_owner:npg_" + "Q" * 14
              + "@ep-x.neon.tech/db\nNVIDIA_API_KEY=nvapi-" + "k" * 30 + "\n")
    names = {n for n, _ in findings_in(sample)}
    assert {"google-api-key", "neon-password", "postgres-url-with-password", "nvidia-nim-key"} <= names


def test_scanner_ignores_the_documented_placeholders():
    assert findings_in("DATABASE_URL=postgresql://user:password@localhost:5432/db\n"
                       "DATABASE_URL=postgresql://${DB_POSTGRES_USER:-prc_user}:${DB_POSTGRES_PASSWORD:?set}@postgres:5432/x\n"
                       "PG_PASSWORD=changeme\n") == []


@pytest.mark.parametrize("path", _tracked_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_tracked_file_holds_no_credential(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        pytest.skip("unreadable")
    hits = findings_in(text)
    assert not hits, f"credential-shaped content in {path.relative_to(ROOT)}: {hits}"
