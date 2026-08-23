# Plan 01: Fix Cython Export of AlmgrenChrissCostModel

## Finding

**C-04**: `AlmgrenChrissCostModel` (and `SqrtCostModel`, `CostModel`) are defined in `bt/core.py` and imported in `bt/__init__.py`, but the compiled Cython `.so` file does not export them. Users get `ImportError` when trying to use these classes.

## Context

The Cython build system uses `hatch-cython` which compiles `bt/core.py` to C and then to a shared object. The compilation configuration in `pyproject.toml` excludes some symbols from the Cython-generated C output because they reference Python objects that the Cython compiler cannot handle in the current configuration.

Evidence:
```python
# bt/core.py:2127-2211
class CostModel:
    ...

class SqrtCostModel(CostModel):
    ...

class AlmgrenChrissCostModel(CostModel):
    ...
```

```python
# bt/__init__.py:6-19
from .core import (
    Algo,
    AlgoStack,
    AlmgrenChrissCostModel,  # ← will fail at runtime
    ...
)
```

```
# Compiled .so lacks these symbols
>>> import bt.core
>>> hasattr(bt.core, 'AlmgrenChrissCostModel')
False
```

## Files in Scope

| File | Action |
|------|--------|
| `bt/core.py` | No changes — definitions are correct |
| `bt/__init__.py` | No changes — exports are correct |
| `pyproject.toml` | **Modify** — add Cython `define_macros` or adjust build config to include CostModel classes |

## Out of Scope

- Changing the build backend from hatchling
- Modifying tests
- Adding new features

## Implementation Steps

### Step 1: Investigate current Cython build config

Read `pyproject.toml` lines 63-88. Understand why CostModel classes are excluded.

The current config:
```toml
[tool.hatch.build.targets.wheel.hooks.cython.options.files]
targets = ["*/core.py"]
exclude = [
    "*/__init__.py",
    "*/algos.py",
    "*/backtest.py",
]
```

Check if there's an explicit exclusion of CostModel or if it's an implicit Cython limitation.

**Verification**: Run `python3 -c "import cython; print(cython.__version__)"` and note version.

### Step 2: Add CostModel to Cython compilation

Option A: Add `--embedsignatures` and ensure classes are included:
```bash
cython --embedsignatures -3 bt/core.py
```

Option B: If the issue is that CostModel classes use Cython `@cy.locals` decorators, ensure they are visible:
```python
# In bt/core.py, add @cy.ccall before each method if needed
```

**Likely root cause**: The Cython compiler may be excluding these classes because they define methods with complex signatures or because they're at module level after the performance-critical loop code.

**Fix**: Add these classes to the Cython compilation by either:
1. Moving them before the `@cy.locals` decorated functions (Cython processes them first)
2. Adding an explicit `__all__` in `bt/core.py` listing all exports
3. Using `# cython: boundchecks=False` and ensuring the classes don't trigger Cython warnings

### Step 3: Verify the fix

```bash
# Rebuild Cython
python3 -c "from Cython.Build import cythonize; cythonize('bt/core.py')"
python3 -c "from setuptools import Extension, setup; ext = Extension('bt.core', sources=['bt/core.c']); setup(ext_modules=ext, script_args=['build_ext', '--inplace'])"

# Verify exports
.venv/bin/python -c "from bt import AlmgrenChrissCostModel; print(AlmgrenChrissCostModel)"
.venv/bin/python -c "from bt import SqrtCostModel; print(SqrtCostModel)"
.venv/bin/python -c "from bt import CostModel; print(CostModel)"

# Run tests
python3 -m pytest tests/ -q
```

**Expected**: All 182 tests pass, three new imports succeed.

## Status: ✅ COMPLETED

**Date**: 2026-08-23  
**Actual fix**: The issue was not that CostModel classes were excluded from Cython compilation — they *were* compiled correctly. The real problem was twofold:

1. **Missing `editables` dependency**: `hatchling`'s editable install backend requires the `editables` package, which was not in `pyproject.toml`'s dev dependencies. Installing it fixed the metadata generation step.
2. **Flat-layout ambiguity**: `raw/` and `plans/` directories in the repo root were detected by setuptools as top-level packages alongside `bt/`, causing the build to abort. Added `[tool.setuptools.packages.find]` with `include = ["bt*"]` to disambiguate.
3. **Stale .so for Python 3.13**: The existing `.so` was compiled for Python 3.12; rebuilding it for 3.13 resolved the `_PyThreadState_UncheckedGet` symbol error.

**Changes made**:
- `pyproject.toml` +4 lines: added `[tool.setuptools.packages.find] where = ["."] include = ["bt*"]`
- `.venv`: installed `editables` package

**Verification**:
```
.venv/bin/python3.13 -c "from bt import AlmgrenChrissCostModel, SqrtCostModel, CostModel; print('OK')"
# Output: OK

.venv/bin/python3.13 -m pytest tests/ -q
# 182 passed, 39 warnings in 12.93s
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Build | `python3 -m pip install --no-build-isolation -e .` | Successful editable install |
| Import | `.venv/bin/python -c "from bt import AlmgrenChrissCostModel, SqrtCostModel, CostModel; print('OK')"` | Output: `OK` |
| Test | `python3 -m pytest tests/test_core.py -q` | All pass |
| Lint | `python3 -m ruff check bt` | No errors |

## Test Plan

No new tests needed — existing tests already reference these classes (they fail during collection, which is the bug). After the fix, the existing test collection should succeed.

If you want to be thorough, add a simple test:
```python
# tests/test_core.py (add at end)
def test_costmodel_import():
    from bt import AlmgrenChrissCostModel, SqrtCostModel, CostModel
    assert CostModel is not None
    assert SqrtCostModel is not None
    assert AlmgrenChrissCostModel is not None
```

## Maintenance Note

- Any new Cython-compiled class in `core.py` must be verified to export correctly.
- The `@cy.locals` decorator pattern works fine for these classes — the issue is build configuration.
- Document this fix in `CHANGELOG.md` under "Bug Fixes".

## Escape Hatches

- **If Cython won't compile these classes**: Fall back to keeping them as pure Python. Move the classes out of `core.py` into a new `bt/costs.py` file that is NOT Cythonized. This avoids the build complexity while preserving functionality.
- **If hatchling editable install remains broken**: Create a standalone `setup.py` that compiles only `core.py` without hatchling, as a workaround until hatch-cython is fixed.

## Evidence References

- `bt/core.py:2127-2211` — CostModel, SqrtCostModel, AlmgrenChrissCostModel definitions
- `bt/__init__.py:6-19` — Import statements that fail
- `pyproject.toml:63-88` — Cython build configuration
- `tests/test_core.py:10-14` — Test imports that fail at collection