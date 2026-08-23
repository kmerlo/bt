# Plan 03: Migrate from pip to uv

## Finding

**X-02**: The Makefile, CI, and documentation use `pip`/`python -m pip` for package management. The user explicitly requested `uv` as the package manager. `uv` is significantly faster (10-100x) and resolves dependency conflicts better.

## Context

Current Makefile usage:
```makefile
develop:
    python -m pip install -e .[dev]
```

CI usage (`.github/workflows/build.yaml`):
```yaml
run: make develop
```

## Files in Scope

| File | Action |
|------|--------|
| `Makefile` | Replace all `python -m pip install` with `uv pip install` or `uv sync` |
| `.github/workflows/build.yaml` | Add `uv` setup step |
| `.github/workflows/deploy.yaml` | Add `uv` setup step |
| `.github/workflows/regression.yaml` | Add `uv` setup step |
| `README.md` | Update install instructions |
| `pyproject.toml` | Add `[tool.uv]` table with workspace config |

## Out of Scope

- Migrating to `uv` workspace mode (out of scope for v1)
- Changing build backend
- Modifying dependency versions

## Implementation Steps

### Step 1: Update `Makefile`

Replace all pip invocations with uv equivalents:

```makefile
# Before
develop:
    python -m pip install -e .[dev]

test:
    python -m pytest -vvv tests --cov=bt --junitxml=python_junit.xml --cov-report=xml --cov-branch --cov-report term

lint:
    python -m ruff check bt docs/source/conf.py
    python -m ruff format --check bt docs/source/conf.py

fix:
    python -m ruff check --fix bt docs/source/conf.py
    python -m ruff format bt docs/source/conf.py

dist:
    python -m pip install --upgrade build
    python -m build --sdist --wheel
    python -m twine check dist/*
```

```makefile
# After
develop:
    uv pip install --system -e ".[dev]"

test:
    uv run pytest -vvv tests --cov=bt --junitxml=python_junit.xml --cov-report=xml --cov-branch --cov-report term

lint:
    uv run ruff check bt docs/source/conf.py
    uv run ruff format --check bt docs/source/conf.py

fix:
    uv run ruff check --fix bt docs/source/conf.py
    uv run ruff format bt docs/source/conf.py

dist:
    uv pip install --system build twine
    uv run build
    uv run twine check dist/*
```

**Note**: Use `uv run` to avoid creating a virtual environment — it runs commands in the project context.

### Step 2: Add `uv` setup to CI

In each workflow file, add after `actions/setup-python`:

```yaml
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true
    cache-dependency-glob: "pyproject.toml"

- name: Install dependencies
  run: uv pip install --system -e ".[dev]"
```

Remove any redundant `python -m pip install` steps.

### Step 3: Add `[tool.uv]` to `pyproject.toml`

```toml
[tool.uv]
# Ensure editable installs work with uv
package = false
# Disable default dependencies for dev install
default-groups = []
```

### Step 4: Update `README.md`

Replace any `pip install` instructions with:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install bt with dev deps
uv pip install --system -e ".[dev]"
```

### Step 5: Verify

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Test make commands
make test
make lint
make develop
```

## Status: ✅ COMPLETED

**Date**: 2026-08-23  
**Fix**: Migrated Makefile and CI workflows from `pip`/`python -m` to `uv`.

**Changes**:
- `Makefile`: all targets now use `uv run` (pytest, ruff, build, twine, http.server, jupyter) and `uv sync --all-groups --all-extras` for `develop`
- `pyproject.toml`: added `[tool.uv]` with `package = false`
- `.github/workflows/build.yaml`: added `astral-sh/setup-uv@v3`, switched cibuildwheel to `uv run`
- `.github/workflows/deploy.yaml`: added `setup-uv`, switched `pip install` to `uv pip install`, cibuildwheel to `uv run`
- `.github/workflows/regression.yaml`: added `setup-uv`, switched `pip install` to `uv pip install`
- `README.md`: added uv install instructions, updated contributing section
- `bt/backtest.py`: fixed import order (`import inspect` before `from copy import deepcopy`)

**Verification**:
```
make test   → 185 passed
make lint   → All checks passed
make dist   → sdist + wheel built, twine check passed
make fix    → 1 file reformatted (import order)
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Install uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | uv installed to `~/.local/bin/uv` |
| Test develop | `make develop` | Editable install succeeds |
| Test lint | `make lint` | All checks pass |
| Test build | `make dist` | sdist and wheel built |

## Test Plan

No new tests needed. Existing tests should pass with `uv run pytest`.

Add a manual verification:
```bash
# Confirm uv is being used
which uv
uv --version
```

## Maintenance Note

- `uv` caches dependencies globally by default. This is usually desired.
- The `--system` flag ensures packages install into the active Python environment (matching previous behavior).
- CI caches are improved with uv's built-in caching (`enable-cache: true`).
- If the project later moves to a virtual environment approach, remove `--system`.

## Escape Hatches

- **If uv causes issues on Windows/macOS**: Keep a `Makefile.pip` fallback and update CI to use it conditionally.
- **If `uv run` has issues with Cython builds**: Use `uv pip install` for deps and `make build_dev` separately.
- **If anyone objects to uv**: Add a note in README explaining why uv was chosen (speed, reliability) and keep pip as fallback.

## Evidence References

- `Makefile` — current pip usage
- `.github/workflows/build.yaml` — CI install steps
- User request: "usa uv come package manager"