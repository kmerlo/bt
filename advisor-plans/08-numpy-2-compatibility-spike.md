# Plan 08: NumPy 2.x Compatibility Spike (Design Plan)

## Status: ✅ COMPLETED

**Date**: 2026-08-23  
**Finding**: The project already runs on NumPy 2.5.2 with zero issues. No deprecated APIs are used in the codebase.

**Verification**:
```
numpy: 2.5.2 (in .venv, Python 3.12)
uv run python -c "import bt; print('OK')"  → OK
make test                                 → 192 passed
grep for deprecated APIs in bt/           → none found
```

**Changes made**:
- `pyproject.toml`: updated `numpy` pin from `">=1"` to `">=1.26,<3.0"` to explicitly document 2.x support
- `README.md`: added "Requirements" section documenting NumPy ≥ 1.26 / 2.x compatibility

**No code changes needed** — the codebase was already clean of deprecated NumPy APIs (`np.in1d`, `np.round_`, `np.object`, etc. were never used). The existing CI regression workflow already tests against `numpy>=2`.

## Finding

**M-01**: The project pins `numpy>=1` in dependencies. NumPy 2.0 was released in June 2024 with breaking changes:
- Removed deprecated APIs (`np.string_`, `np.unicode_`, `np.object_`, etc.)
- Changed default dtype behavior for some operations
- Cython compatibility issues with newer NumPy C API

The project currently runs on NumPy 1.26.4 (last 1.x release). Migration to 2.x is non-trivial due to Cython compilation.

## Context

NumPy 2.0 breaking changes affecting bt:
1. **C API changes**: Cython extensions compiled against NumPy 1.x may not link with NumPy 2.x
2. **Deprecated types removed**: `np.object` → `object`, `np.string` → `bytes`, etc.
3. **Default dtype changes**: Some operations now default to different dtypes

## Investigation Steps

### Step 1: Audit NumPy usage in codebase

```bash
# Find all numpy imports and usages
grep -rn "np\." bt/ --include="*.py" | grep -v test | sort | uniq
```

Key patterns to check:
- `np.object`, `np.string_`, `np.unicode_` (removed in 2.0)
- `np.mat` (deprecated)
- `np.PINF`, `np.NINF`, `np.PZERO`, `np.NZERO` (removed)
- `np.in1d` (replaced with `np.isin`)
- `np.round_(a)` (replaced with `np.round(a)`)
- `np.cumproduct` (replaced with `np.cumprod`)
- `np.product` (replaced with `np.prod`)

### Step 2: Create compatibility shim

Create `bt/numpy_compat.py`:
```python
"""NumPy compatibility layer for 1.x and 2.x."""

import numpy as np

# Map removed/rename symbols to their 2.0 equivalents
# These are imported as needed throughout the codebase

# Object/string aliases (removed in 2.0)
try:
    np_object = np.object_
except AttributeError:
    np_object = object

try:
    np_string = np.bytes_
except AttributeError:
    np_string = bytes

# Check for deprecated aliases
if hasattr(np, "PINF"):
    np_PINF = np.PINF
else:
    np_PINF = np.inf

if hasattr(np, "NINF"):
    np_NINF = np.NINF
else:
    np_NINF = -np.inf

# isin vs in1d
if hasattr(np, "isin"):
    np_isin = np.isin
else:
    np_isin = np.in1d
```

### Step 3: Test with NumPy 2.x

```bash
# Install NumPy 2.x
uv pip install --system "numpy>=2.0"

# Try to import bt
python -c "import bt"

# Run tests
python -m pytest tests/ -q
```

### Step 4: Fix any failures

Common fixes needed:
1. Replace `np.object` with `object`
2. Replace `np.string_` with `bytes`
3. Replace `np.in1d` with `np.isin`
4. Update Cython `.c` files or force recompile
5. Fix any dtype mismatch errors

### Step 5: Update dependencies

In `pyproject.toml`:
```toml
[project]
dependencies = [
    "ffn>=1.1.2",
    "numpy>=1.26,<3.0",  # Compatible with both 1.x and 2.x
    ...
]
```

Add test matrix in CI:
```yaml
strategy:
  matrix:
    numpy-version: ["1.26", "2.0"]
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Check NumPy | `python -c "import numpy; print(numpy.__version__)"` | 1.x or 2.x |
| Import test | `python -c "import bt"` | No ImportError |
| Test suite | `python -m pytest tests/ -q` | All pass |
| Lint | `python -m ruff check bt` | No errors |

## Test Plan

1. Install NumPy 1.26: verify all tests pass (baseline)
2. Install NumPy 2.0: verify all tests pass (target)
3. Test with mixed: install bt against 1.x, run with 2.x
4. Test edge cases: operations that changed dtype behavior

## Maintenance Note

- **Cython rebuild**: When upgrading NumPy, the Cython `.c` file may need regeneration if the NumPy C API changed.
- **Deprecation warnings**: Turn on `-Werror` for deprecation warnings during the migration to catch issues early.
- **User impact**: Users with NumPy 2.x installed should be able to use bt immediately after this fix.

## Escape Hatches

- **If Cython won't compile with NumPy 2.x**: Keep NumPy pinned to `<2.0` until a Cython release supports the new API.
- **If compatibility shim is too complex**: Document that NumPy 1.x is required, and add a version check at import time.
- **If ffn doesn't support NumPy 2.x yet**: Wait for ffn to update its dependencies.

## Evidence References

- `pyproject.toml:38-41` — Current dependencies (`numpy>=1`)
- NumPy 2.0 migration guide: https://numpy.org/doc/stable/numpy_2_0_migration_guide.html
- `bt/core.py` — Cython compilation target