# Plan 09: Split core.py God Module (Design Plan)

## Finding

**D-01**: `bt/core.py` is 2211 lines with 121 symbols. It contains:
- Tree node classes (Node, StrategyBase, SecurityBase)
- Cost model classes (CostModel, SqrtCostModel, AlmgrenChrissCostModel)
- Algo base classes (Algo, AlgoStack)
- Fixed income classes (FixedIncomeStrategy, FixedIncomeSecurity, etc.)

This god module causes:
- Long Cython rebuild times (any change to core.py requires full recompilation)
- Difficulty adding type hints (too many interconnected classes)
- Hard to test in isolation
- Hard to understand the module boundaries

## Context

The file serves multiple responsibilities that could be separated:
1. **Tree data structures**: Node, StrategyBase, SecurityBase
2. **Cost models**: CostModel, SqrtCostModel, AlmgrenChrissCostModel
3. **Algo framework**: Algo, AlgoStack
4. **Fixed income**: FixedIncomeStrategy, FixedIncomeSecurity, etc.

## Proposed Split

```
bt/core/
├── __init__.py      # Re-exports from all submodules
├── node.py          # Node base class
├── strategy.py      # StrategyBase, FixedIncomeStrategy
├── security.py      # SecurityBase, FixedIncomeSecurity, HedgeSecurity, CouponPayingSecurity
├── algo.py          # Algo, AlgoStack
└── costs.py         # CostModel, SqrtCostModel, AlmgrenChrissCostModel
```

## Design Steps

### Step 1: Define module boundaries

Analyze `core.py` to identify clear separation points:

**node.py** (~400 lines):
```python
class Node:
    """Base tree node."""
    # All Node methods and properties
```

**strategy.py** (~800 lines):
```python
class StrategyBase(Node):
    """Strategy node with capital allocation logic."""
    # All StrategyBase methods
    # Inherit Node from node.py
```

**security.py** (~600 lines):
```python
class SecurityBase(Node):
    """Security node with position tracking."""
    # All SecurityBase methods
    # Inherit Node from node.py

class FixedIncomeSecurity(SecurityBase):
    ...

class HedgeSecurity(SecurityBase):
    ...

class CouponPayingSecurity(SecurityBase):
    ...
```

**algo.py** (~300 lines):
```python
class Algo:
    """Base algorithm class."""
    def __call__(self, target):
        raise NotImplementedError

class AlgoStack(Algo):
    """Stack of algorithms."""
    ...
```

**costs.py** (~200 lines):
```python
class CostModel:
    """Base cost model."""
    def cost(self, q, p, V, sigma):
        raise NotImplementedError

class SqrtCostModel(CostModel):
    ...

class AlmgrenChrissCostModel(CostModel):
    ...
```

### Step 2: Implement gradual migration

Phase 1: Create new modules with imports from old location
```python
# bt/core/node.py (NEW)
from bt.core import Node  # Temporary circular import, will be resolved
```

Phase 2: Move code, update imports within bt
```python
# Update bt/core/strategy.py
from bt.core.node import Node
```

Phase 3: Update public API (`bt/__init__.py`)
```python
from .core.node import Node
from .core.strategy import StrategyBase
from .core.security import SecurityBase
from .core.algo import Algo, AlgoStack
from .core.costs import CostModel, SqrtCostModel, AlmgrenChrissCostModel
```

### Step 3: Consider Cython implications

The Cython compilation currently covers the entire `core.py`. After splitting:
- **Option A**: Compile each module separately (more build complexity)
- **Option B**: Keep `core.py` as a single Cython target but with internal imports
- **Option C**: Only Cythonize the performance-critical parts (Node.update, SecurityBase.update)

**Recommendation**: Start with Option B — keep single `.so` but reorganized modules. The Cython compilation can remain on a single `core.py` file that imports from submodules, or gradually migrate to incremental compilation.

### Step 4: Verify no behavior changes

After each phase:
```bash
python -m pytest tests/test_core.py -q
python -m pytest tests/test_algos.py -q
python -m pytest tests/test_backtest.py -q
```

## Risks

| Risk | Mitigation |
|------|------------|
| Circular imports | Use relative imports within `bt.core.*`, absolute imports from outside |
| Cython recompilation time | Only recompile after final phase, not during migration |
| Breaking external users | Maintain `bt.core` namespace — users importing from `bt.core.StrategyBase` still work |

## Verification Commands

| Phase | Command | Expected |
|-------|---------|----------|
| After step 1 | `python -c "from bt.core.node import Node; print(Node)"` | Class imported |
| After step 2 | `python -m pytest tests/test_core.py -q` | All pass |
| After step 3 | `python -m pytest tests/ -q` | All 182+ pass |
| Import compatibility | `python -c "from bt import StrategyBase; from bt.core import StrategyBase"` | Both work |

## Test Plan

1. Unit tests for each new submodule (copy relevant tests from `test_core.py`)
2. Integration test: run full `test_core.py` against new module structure
3. Import test: verify all public API imports still work

## Maintenance Note

- This is a **refactor with no behavior changes** — all tests must pass at each step.
- Document the new module structure in `docs/` or add to `__init__.py` docstring.
- The split should make future contributions easier — new devs can focus on one module at a time.

## Escape Hatches

- **If circular imports become intractable**: Keep some related classes together (e.g., StrategyBase and SecurityBase can stay in `strategy.py` if they reference each other).
- **If Cython compilation breaks**: Revert to single `core.py` and note the split as a future task.
- **If the refactor is too large**: Split only 1-2 modules first (e.g., `costs.py` first, as it's independent).

## Evidence References

- `bt/core.py:1-2211` — Full source (2211 lines, 121 symbols)
- `bt/__init__.py:6-19` — Public API exports
- `tests/test_core.py` — 4053 lines of tests for core functionality