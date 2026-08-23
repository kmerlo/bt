# Plan 05: Add mypy Type Checking

## Finding

**T-01**: The project has no static type checking. Code uses Cython type annotations (`@cy.locals`) but no Python `typing` module annotations. This means:
- IDEs can't provide accurate completions
- Refactors have no safety net
- Type-related bugs are caught only at runtime

## Context

The project supports Python 3.9+, so we can use modern typing features:
- `typing.Self` (Python 3.11+) with `from __future__ import annotations`
- `typing.Protocol` for ABCs
- `typing.TypeVar` for generics
- `typing.cast` for cast expressions

## Files in Scope

| File | Action |
|------|--------|
| `pyproject.toml` | Add `[tool.mypy]` configuration |
| `bt/__init__.py` | Add `__all__` list |
| `bt/core.py` | Add type hints to key classes |
| `bt/algos.py` | Add type hints to key classes |
| `bt/backtest.py` | Add type hints |

## Out of Scope

- Adding types to all 200+ methods (out of scope for v1)
- Changing Cython compilation
- Running mypy on tests

## Implementation Steps

### Step 1: Add mypy configuration to `pyproject.toml`

```toml
[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # Start lenient
disallow_incomplete_defs = false
check_untyped_defs = true
ignore_missing_imports = true
plugins = []
mypy_path = "."
```

### Step 2: Add `__all__` to `bt/__init__.py`

```python
__all__ = [
    "Algo",
    "AlgoStack",
    "AlmgrenChrissCostModel",
    "Backtest",
    "CostModel",
    "CouponPayingHedgeSecurity",
    "CouponPayingSecurity",
    "FixedIncomeSecurity",
    "FixedIncomeStrategy",
    "HedgeSecurity",
    "Result",
    "Security",
    "SqrtCostModel",
    "Strategy",
    "is_zero",
    "run",
]
```

### Step 3: Add types to key classes in `bt/core.py`

Start with the most-used classes:

```python
from __future__ import annotations
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

T = TypeVar("T", bound="Node")

class Node:
    name: str
    parent: Node
    root: Node
    children: Dict[str, Node]
    now: Optional[Any]  # datetime or int index
    stale: bool
    _price: float
    _value: float
    _weight: float
    _issec: bool
    _fixed_income: bool
    integer_positions: bool
    
    def __init__(self, name: str, parent: Optional[Node] = None, 
                 children: Optional[Iterable[Union[str, Node]]] = None) -> None:
        ...
```

### Step 4: Add types to `bt/backtest.py`

```python
from typing import Any, Callable, Dict, List, Optional, Union

class Backtest:
    strategy: Strategy
    data: pd.DataFrame
    dates: pd.DatetimeIndex
    initial_capital: float
    name: Optional[str]
    stats: Any  # ffn.PerformanceStats
    has_run: bool
    
    def __init__(self, strategy: Union[Strategy, Node], data: pd.DataFrame,
                 name: Optional[str] = None,
                 initial_capital: float = 1_000_000.0,
                 commissions: Optional[Union[Callable[[float, float], float], CostModel]] = None,
                 integer_positions: bool = True,
                 progress_bar: bool = False,
                 additional_data: Optional[Dict[str, Any]] = None,
                 volume: Optional[pd.DataFrame] = None,
                 volatility: Optional[pd.DataFrame] = None) -> None:
        ...
```

### Step 5: Run mypy and fix critical errors

```bash
uv run mypy bt/ --show-error-codes
```

Fix errors in priority order:
1. `return` type mismatches
2. `Callable` signature mismatches
3. Missing imports

Leave `Any` annotations where types are genuinely complex (e.g., Cython internals).

### Step 6: Add mypy to CI

In `.github/workflows/build.yaml`, add before tests:
```yaml
- name: Type check
  run: uv run mypy bt/
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Config | `uv run mypy --version` | mypy version printed |
| Initial run | `uv run mypy bt/ --show-error-codes` | Errors listed |
| After fixes | `uv run mypy bt/` | Zero errors (or acceptable baseline) |
| Full CI | `python -m pytest tests/ -q && uv run mypy bt/` | Both pass |

## Test Plan

No new tests needed. mypy runs on the source tree.

Add a mypy-specific test in CI:
```yaml
- name: Type check
  run: uv run mypy bt/ bt/backtest.py
```

## Maintenance Note

- **Gradual typing**: Don't try to type everything at once. Add types to new code and to high-impact areas first.
- **Cython interop**: Cython-compiled code may not be fully type-checkable. Use `# type: ignore` sparingly and with reason.
- **`from __future__ import annotations`**: Use this to enable postponed evaluation, which avoids forward-reference issues.

## Escape Hatches

- **If mypy errors are too many to fix at once**: Set `disallow_untyped_defs = false` and `warn_unused_ignores = true` as a temporary baseline.
- **If Cython types conflict with mypy**: Use `# type: ignore[misc]` on Cython-specific lines.
- **If mypy slows down CI**: Run mypy only on push to master, not on PRs.

## Evidence References

- `bt/core.py` — 2211 lines, no type hints
- `bt/backtest.py:162-201` — Key public API, prime candidate for typing
- `bt/__init__.py` — No `__all__` list
- Project supports Python 3.9+ → can use `X | Y` union syntax