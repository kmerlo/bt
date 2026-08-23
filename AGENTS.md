# AGENTS.md

This file provides guidance to Agnes (opencode) when working with code in this repository.

## Project Overview

**bt** is a flexible backtesting framework for Python used to test quantitative trading strategies. It provides a tree-based architecture where strategies can contain both securities and other strategies, enabling complex multi-layered portfolio constructions.

The framework is built on top of [ffn](https://github.com/pmorissette/ffn) - a financial function library for Python.

Documentation: http://pmorissette.github.io/bt

## Architecture

### Core Modules

- **`bt/core.py`** (~900 lines): Core building blocks including:
  - `Node`: Base tree node class (parent of both strategies and securities)
  - `Strategy` / `StrategyBase`: Strategy logic containers that execute AlgoStacks
  - `Security` / `SecurityBase`: Security wrappers with price/value tracking
  - `Algo` / `AlgoStack`: Algorithm building blocks for strategy logic
  - `FixedIncomeStrategy`, `FixedIncomeSecurity`, `HedgeSecurity`, `CouponPayingSecurity`: Fixed-income variants

- **`bt/algos.py`** (~1600 lines): Collection of built-in algorithms (RunMonthly, SelectAll, WeighEqually, Rebalance, etc.)

- **`bt/backtest.py`** (~500 lines): Backtest orchestration and results analysis

### Tree Structure

The tree structure is central to bt's design:
- Each `Node` has a parent, children, and a root
- `Strategy` nodes can contain both `Security` nodes and other `Strategy` nodes
- This enables nested strategies (e.g., a momentum sub-strategy within a main portfolio)
- Each node maintains its own price index reflecting its value over time

### Algo Execution Flow

1. `Backtest.run()` iterates through dates
2. On each date, the strategy's `AlgoStack` runs sequentially
3. Each `Algo` returns `True` (continue) or `False` (stop stack execution)
4. `Rebalance` algos adjust positions based on weights set by earlier algos

### Cython Performance

`bt/core.py` is Cythonized for performance. The build process:
- `bt/core.py` → Cython → `bt/core.c` → compiled `.so`
- Type declarations (e.g., `@cy.locals(x=cy.double)`) mark performance-critical sections
- If Cython is unavailable, falls back to the pre-generated `bt/core.c`

**Known fix** (applied 2026-08-23): The editable install requires:
- `editables` package installed (not declared in pyproject.toml — must be added manually to .venv)
- `[tool.setuptools.packages.find]` block in `pyproject.toml` to disambiguate flat-layout packages

## Common Commands

```bash
# Setup development environment
make develop          # Install package with dev dependencies in editable mode

# Build Cython extensions (required after modifying bt/core.py)
make build_dev        # Build extensions in-place

# Testing
make test             # Run all tests with coverage
python -m pytest tests/test_core.py -v                    # Run specific test file
python -m pytest tests/test_core.py::test_node_tree1 -v   # Run single test

# Linting and formatting (uses Ruff, line-length: 180)
make lint             # Check linting and formatting
make fix              # Auto-fix issues and format code

# Cleanup
make clean            # Remove build artifacts, .so files, and generated .c files

# Documentation
make docs             # Build Sphinx documentation
make serve            # Serve docs locally on port 9087

# Distribution
make dist             # Build sdist and check with twine
make upload           # Upload to PyPI (requires credentials)
```

## Key Dependencies

- `ffn>=1.1.2`: Financial function library (data fetching, performance metrics)
- `pandas`: Time series data structures
- `numpy`: Numerical operations
- `matplotlib`: Charting
- `cython`: Performance compilation (dev)
- `ruff`: Linting and formatting (dev)
- `pytest`, `pytest-cov`: Testing (dev)
- `editables`: Required by hatchling editable installs (not in pyproject.toml)

## Testing Structure

Tests are in `tests/`:
- `test_core.py`: Tests for Node, Strategy, Security, Algo classes
- `test_algos.py`: Tests for built-in algorithms
- `test_backtest.py`: Tests for Backtest and Result classes

All tests use pytest. The project uses mocked data rather than requiring network access.

## Code Style

- **Line length**: 180 characters (configured in `pyproject.toml`)
- **Linter**: Ruff (replaces flake8, black, isort)
- `__init__.py` files ignore F401/F403 (unused imports) due to re-export pattern

## Examples

The `examples/` directory contains both `.py` scripts and `.ipynb` notebooks demonstrating:
- Basic buy-and-hold strategies
- Equal Risk Contribution (ERC)
- Pairs trading
- Fixed income strategies
- Strategy combination (nested strategies)
- Target volatility approaches

## Creating New Algos

To add a new algo:
1. Inherit from `bt.core.Algo`
2. Implement `__call__(self, target)` returning `True` or `False`
3. Access target's state via `target.now` (current date), `target.temp` (temp storage), `target.children`, etc.
4. Use the `@run_always` decorator if the algo should run regardless of stack failures

## Release Process

1. Update version in `setup.py` and `bt/__init__.py`
2. Update `CHANGELOG` if applicable
3. Run `make test` and `make lint`
4. Run `make dist` to verify packaging
5. Create GitHub release with tag
6. `make upload` to publish to PyPI

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

---

## Agent Directives (opencode-specific)

### Plan Completion Protocol

When an advisor-plans plan is fully implemented and verified:

1. **Mark the plan file as completed** — add a `## Status: ✅ COMPLETED` section at the top with the actual fix details, date, and verification commands used.
2. **Update advisor-plans/README.md** — change the plan's status from `READY` to `✅ DONE` in the execution table.
3. **Commit and push** — stage only the relevant changed files, write a concise commit message, and push to the remote.
4. **Never skip the commit** — even if the change feels minor, every completed plan must be committed.

### Code Quality

- Run `make lint` and `make test` before committing.
- Prefer the shortest working diff; avoid adding code that isn't strictly required.
- Do not add comments unless the user asks for them.
- Follow the existing code style (Ruff, line-length 180).

### Build Notes

- After editing `bt/core.py`, always rebuild: `python3 -m Cython.Build.cythonize -3 bt/core.py && python3 -m setuptools build_ext --inplace`
- The editable pip install may fail if `editables` is missing from `.venv`. Install it with `uv pip install editables`.
- The `[tool.setuptools.packages.find]` block in `pyproject.toml` is required for editable installs on Python 3.13+.
- The `.python-version` file pins the venv to Python 3.12; Python 3.14 has a pandas ABI mismatch.

## Documentazione esperienziale

I file in `docs/` contengono la cronaca dei problemi complessi risolti su
questo progetto. Ogni volta che si incontra un bug ostico o si impara una
lezione su lightweight-charts / React / FastAPI, si aggiorna un file esistente
o se ne crea uno nuovo in `docs/`.

Regole:
- AGENTS.md resta un quick-reference scansionabile (comandi, architettura,
  convenzioni). Niente deep-dive tecnici.
- I dettagli delle soluzioni vanno in `docs/`: cosa NON funzionava, cosa è
  stato tentato, perché falliva, soluzione finale, riferimenti alle righe di
  codice.
- Se un fix tocca sia frontend che backend, creare un unico file che copra
  entrambi.
- Committare sempre anche i file in `docs/` insieme al codice che risolve il
  problema.

### Prefissi dei file in `docs/`

Ogni file in `docs/` ha un prefisso che ne indica il tipo:

| Prefisso | Tipo | Esempi |
|----------|------|--------|
| `FIX-` | Cronaca di un bug/problema risolto (cosa NON funzionava, cosa è stato tentato, perché falliva, soluzione, righe di riferimento) | `FIX-DB_MIGRATION_FAILURES.md`, `FIX-MULTI_CHART_SYNC.md` |
| `GUIDE-` | Documentazione "viva" che descrive come funziona qualcosa e cresce nel tempo (integrazioni, architettura, logiche, how-to) | `GUIDE-INTEGRAZIONE_PINETS.md`, `GUIDE-ARCHITETTURA_TECNICA.md` |
| `MANUALE-` | Manuale utente | `MANUALE-UTENTE.md` |
| `ANALISI-` | Analisi/audit one-off (pre-merge, studi, report) | `ANALISI-MERGE.md`, `ANALISI-improve.md` |
| `NOTE-` | Appunti e verbali di sessione | `NOTE-appunti_opencode.md` |

Regole per le nuove creazioni:
- Bug fix / lezione appresa → `FIX-<nome>.md`. Descrizione di un
  comportamento o integrazione → `GUIDE-<nome>.md`. In caso di dubbio usare
  `FIX-` (la cronaca di problemi è il caso d'uso principale della cartella).
- Se un file cambia natura, rinominarlo col prefisso giusto e aggiornare tutti
  i riferimenti.
- Ogni creazione/rinomina/cancellazione va registrata in `docs/README.md`
  (l'indice): mai lasciare l'indice stantio.
