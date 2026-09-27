"""F9 - outdated / inconsistent Python dependency pins (CWE-1104).

The webserver is installed by ``background_installer.sh`` from inline pip
arguments while ``requirements.txt`` claims a different, much older set of
versions. Werkzeug 2.3.7 (the installer's pin) is affected by
CVE-2023-46136 (multipart parser resource exhaustion, fixed in 2.3.8).

These tests assert that:

* every third-party module imported by ``webserver/*.py`` is pinned in
  ``requirements.txt`` with an exact ``==`` version;
* every ``pip install`` in ``background_installer.sh`` is driven by
  ``requirements.txt`` (or repeats its pins verbatim);
* every pin is at or above the patched floor and below the next major
  (the runtime targets Flask 2.x / Werkzeug 2.x / pymodbus 2.5.x).
"""
import ast
import re
import shlex
from pathlib import Path

import pytest

from conftest import REPO_ROOT, WEBSERVER_DIR

REQUIREMENTS = REPO_ROOT / "requirements.txt"
INSTALLER = REPO_ROOT / "background_installer.sh"

# top-level import name -> PyPI distribution (normalised, lower-case, '-')
MODULE_TO_DIST = {
    "flask": "flask",
    "flask_login": "flask-login",
    "flask_jwt_extended": "flask-jwt-extended",
    "flask_sqlalchemy": "flask-sqlalchemy",
    "werkzeug": "werkzeug",
    "pymodbus": "pymodbus",
    "serial": "pyserial",
    "dotenv": "python-dotenv",
}

# (inclusive floor, exclusive ceiling). Floors are the first release that
# closes the known issue; ceilings keep the runtime on the API line it targets.
PATCHED_RANGES = {
    "werkzeug": ("2.3.8", "3"),        # CVE-2023-46136 fixed in 2.3.8
    "flask": ("2.3.3", "3"),
    "flask-login": ("0.6.2", "1"),
    "pymodbus": ("2.5.3", "3"),
    "pyserial": ("3.5", "4"),
    "flask-jwt-extended": ("4.5.3", "5"),
    "flask-sqlalchemy": ("3.1.1", "4"),
    "python-dotenv": ("1.0.1", "2"),
}

PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(==|>=|<=|~=|!=|<|>)?\s*([0-9][^\s;]*)?\s*(?:;.*)?$")


def normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def version_tuple(v):
    return tuple(int(p) for p in re.findall(r"\d+", v))


def parse_requirement(spec):
    """Return (dist, operator, version) for a single requirement string."""
    m = PIN_RE.match(spec.strip())
    assert m, "unparseable requirement %r" % spec
    return normalise(m.group(1)), m.group(2), m.group(3)


def load_requirements(path=REQUIREMENTS):
    reqs = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        dist, op, ver = parse_requirement(line)
        reqs[dist] = (op, ver)
    return reqs


def runtime_imports():
    """Third-party top-level modules imported anywhere in webserver/*.py."""
    mods = set()
    for py in WEBSERVER_DIR.glob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
    return {m for m in mods if m in MODULE_TO_DIST}


def pip_install_invocations():
    """Every ``pip install ...`` in the installer as a list of argv tails.

    Returns a list of (line_number, [args after 'install']).
    """
    calls = []
    for lineno, raw in enumerate(INSTALLER.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if "pip install" not in line and "pip3 install" not in line:
            continue
        argv = shlex.split(line.replace("$OPENPLC_DIR", str(REPO_ROOT)))
        idx = argv.index("install")
        calls.append((lineno, argv[idx + 1:]))
    return calls


def installer_pins(args):
    """Resolve one pip-install argv tail to {dist: (op, version)}.

    ``-r file`` is expanded through ``load_requirements``; bare package
    names are recorded with (None, None) so callers can flag them.
    """
    pins = {}
    it = iter(args)
    for tok in it:
        if tok in ("-r", "--requirement"):
            pins.update(load_requirements(Path(next(it))))
        elif tok.startswith("-r") and len(tok) > 2:
            pins.update(load_requirements(Path(tok[2:])))
        elif tok.startswith("--requirement="):
            pins.update(load_requirements(Path(tok.split("=", 1)[1])))
        elif tok.startswith("-"):
            continue
        else:
            dist, op, ver = parse_requirement(tok)
            pins[dist] = (op, ver)
    return pins


# ---------------------------------------------------------------------------

PIP_INSTALLS = pip_install_invocations()

def test_every_runtime_import_is_pinned_in_requirements():
    reqs = load_requirements()
    expected = {MODULE_TO_DIST[m] for m in runtime_imports()}
    missing = sorted(expected - set(reqs))
    assert not missing, "webserver imports these packages but requirements.txt does not list them: %s" % missing


def test_requirements_use_exact_pins():
    loose = {d: spec for d, spec in load_requirements().items() if spec[0] != "=="}
    assert not loose, "requirements.txt must pin with '==' (no floating ranges): %s" % loose


@pytest.mark.parametrize("dist", sorted(PATCHED_RANGES))
def test_requirements_pin_is_at_patched_version(dist):
    reqs = load_requirements()
    assert dist in reqs, "%s is not listed in requirements.txt" % dist
    op, ver = reqs[dist]
    floor, ceiling = PATCHED_RANGES[dist]
    assert version_tuple(ver) >= version_tuple(floor), "%s==%s is below the patched floor %s" % (dist, ver, floor)
    assert version_tuple(ver) < version_tuple(ceiling), "%s==%s crosses into the next major (%s) - out of scope for F9" % (dist, ver, ceiling)


def test_installer_has_pip_installs():
    assert pip_install_invocations(), "no pip install found in background_installer.sh"


@pytest.mark.parametrize("lineno,args", PIP_INSTALLS, ids=["line%d" % n for n, _ in PIP_INSTALLS])
def test_installer_pip_installs_agree_with_requirements(lineno, args):
    if args and args[-1] == "pip":
        pytest.skip("pip self-upgrade")
    reqs = load_requirements()
    pins = installer_pins(args)
    unpinned = sorted(d for d, (op, ver) in pins.items() if op != "==")
    assert not unpinned, "background_installer.sh:%d installs unpinned packages: %s" % (lineno, unpinned)
    mismatched = {d: (pins[d][1], reqs.get(d, (None, None))[1]) for d in pins if reqs.get(d) != pins[d]}
    assert not mismatched, "background_installer.sh:%d pins differ from requirements.txt (installer, requirements): %s" % (lineno, mismatched)


@pytest.mark.parametrize("lineno,args", PIP_INSTALLS, ids=["line%d" % n for n, _ in PIP_INSTALLS])
def test_installer_webserver_venv_installs_cover_all_runtime_imports(lineno, args):
    if args and args[-1] == "pip":
        pytest.skip("pip self-upgrade")
    pins = installer_pins(args)
    if "flask" not in pins:
        pytest.skip("not the webserver venv install")
    expected = {MODULE_TO_DIST[m] for m in runtime_imports()}
    missing = sorted(expected - set(pins))
    assert not missing, "background_installer.sh:%d webserver install omits: %s" % (lineno, missing)
