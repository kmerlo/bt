# Plan 04: Fix hatch-cython Editable Install with uv

## Finding

**M-02**: `pip install -e .` fails with `hatchling.build` error and Cython compilation failure. This blocks developers from using editable installs, forcing them to use system-wide installs or workarounds.

Root cause: The `hatch-cython` plugin attempts to compile Cython during build metadata generation, but fails due to missing build dependencies or environment issues.

## Context

The build system uses:
- `hatchling` as build backend
- `hatch-cython` as a hook to compile Cython extensions
- `Cython>=0.29.25` as build dependency

Current failure:
```
AttributeError: module 'hatchling.build' has no attribute 'prepare_metadata_for_build_editable'
...
Exception: failed compilation
```

## Files in Scope

| File | Action |
|------|--------|
| `pyproject.toml` | Adjust hatch-cython configuration |
| `Makefile` | Add `build_dev` target using uv directly |
| `README.md` | Document editable install process |

## Out of Scope

- Changing build backend from hatchling
- Removing Cython compilation
- Modifying CI build steps (handled in Plan 03 first)

## Implementation Steps

### Step 1: Understand the failure

The issue is that `hatch-cython`'s `prepare_metadata_for_build_editable` hook is failing during metadata generation. This happens because:
1. The hook tries to compile Cython before the build metadata is generated
2. On some systems, the compilation environment isn't fully set up

### Step 2: Add a dedicated build_dev target to Makefile

```makefile
build_dev:
    # Use uv to install build deps in an isolated environment
    uv pip install --system "hatchling" "hatch-cython" "Cython>=0.29.25" "setuptools"
    # Then do the editable install
    uv pip install --system -e . --no-build-isolation
```

Or alternatively, use `uv build` + `uv pip install`:
```makefile
build_dev:
    uv build --sdist --wheel
    uv pip install --system --no-deps -e .
```

### Step 3: Configure hatch-cython to be less aggressive

In `pyproject.toml`, add:
```toml
[tool.hatch.build.targets.wheel.hooks.cython]
dependencies = ["hatch-cython", "Cython>=0.29.25", "numpy"]
# Skip build isolation for editable installs
strategy = "source"
```

### Step 4: Verify with uv

```bash
# Clean previous artifacts
make clean

# Build dev version
make build_dev

# Verify import
python -c "import bt; print(bt.__version__)"
python -c "from bt import AlmgrenChrissCostModel"  # Also tests Plan 01
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Clean | `make clean` | No `.so` or `.c` files |
| Build | `make build_dev` | Editable install succeeds |
| Import | `python -c "import bt; print(bt.__version__)"` | Version printed |
| Core test | `python -m pytest tests/test_core.py::test_node_tree1 -q` | Passes |

## Test Plan

After build, verify:
1. `import bt` works
2. `from bt import AlmgrenChrissCostModel` works (links to Plan 01)
3. `python -m pytest tests/ -q` passes

## Maintenance Note

- The `--no-build-isolation` flag tells pip to use the current environment's build deps, which is necessary for Cython since it needs to compile against the Python interpreter.
- If the build still fails, check that `cython` is installed: `uv pip install --system cython`.

## Escape Hatches

- **If hatch-cython remains broken**: Switch to manual Cython compilation in the Makefile:
  ```makefile
  build_dev:
      uv pip install --system cython numpy
      python -c "from Cython.Build import cythonize; cythonize('bt/core.py', force=True)"
      python -c "from setuptools import Extension, setup; ext = Extension('bt.core', sources=['bt/core.c'], include_dirs=['numpy.get_include()']); setup(ext_modules=[ext], script_args=['build_ext', '--inplace'])"
  ```
- **If user wants fully automated build**: Create a `setup.py` that handles Cython compilation directly (bypassing hatchling for the compile step).
- **If tests still fail after build**: Check Python version compatibility. The project supports 3.9-3.13; ensure the installed Python version is in that range.

## Evidence References

- `pyproject.toml:63-88` — Current hatch-cython configuration
- `Makefile` — Current build targets
- User-facing error during `pip install -e .`