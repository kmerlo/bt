# Plan 02: Validate Commission Function Signature

## Finding

**C-02**: The `Backtest` constructor accepts a `commissions` parameter but does not validate that it is a callable with the correct signature `fn(quantity, price) -> float`. When users pass an incorrectly-signatured function, they get cryptic `TypeError` errors deep in the backtest execution loop, making debugging difficult.

Evidence:
```python
# bt/backtest.py:162-201
def __init__(self, strategy, data, name=None, initial_capital=1000000.0,
             commissions=None, ...):
    ...
    if isinstance(commissions, bt.core.CostModel):
        self.cost_model = commissions
        ...
    elif commissions is not None:
        self.strategy.set_commissions(commissions)  # No validation here!
```

```python
# bt/core.py:1073-1082
def set_commissions(self, fn):
    self.commission_fn = fn
    for c in self._childrenv:
        if isinstance(c, StrategyBase):
            c.set_commissions(fn)
```

## Context

Users commonly make mistakes like:
- Passing `lambda q: abs(q) * 0.01` (missing `p` parameter)
- Passing `fn(price)` (wrong order)
- Passing a non-callable

All of these would fail later with unhelpful error messages.

## Files in Scope

| File | Action |
|------|--------|
| `bt/backtest.py` | Add signature validation in `Backtest.__init__` |
| `tests/test_backtest.py` | Add test for invalid commission signatures |

## Out of Scope

- Changing the commission API
- Adding validation to CostModel (already validated elsewhere)
- Modifying other modules

## Implementation Steps

### Step 1: Add validation in `Backtest.__init__`

After line 201 (`elif commissions is not None:`), add signature checking:

```python
elif commissions is not None:
    if not callable(commissions):
        raise TypeError(
            f"commissions must be a callable, got {type(commissions).__name__}"
        )
    import inspect
    sig = inspect.signature(commissions)
    params = list(sig.parameters.keys())
    # Allow: fn(q, p), fn(q, p, *args), fn(**kwargs), fn(q, p=0.0), etc.
    # Reject: fn(), fn(q), fn(p), fn(q, p, r)
    if len(params) < 2:
        raise TypeError(
            f"commission function must accept at least 2 arguments "
            f"(quantity, price), got {len(params)}: {params}"
        )
    # Check first two params are not keyword-only
    if all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in list(sig.parameters.values())[:2]):
        raise TypeError(
            f"commission function's first two parameters must be positional"
        )
    self.strategy.set_commissions(commissions)
```

### Step 2: Add tests

In `tests/test_backtest.py`, add a new test class or function:

```python
def test_invalid_commission_type():
    """Commission must be callable."""
    strategy = bt.Strategy("test", [])
    data = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2020", periods=2))
    with pytest.raises(TypeError, match="callable"):
        bt.Backtest(strategy, data, commissions="not_callable")

def test_invalid_commission_signature():
    """Commission must accept at least (q, p)."""
    strategy = bt.Strategy("test", [])
    data = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2020", periods=2))
    
    # Too few params
    with pytest.raises(TypeError, match="at least 2 arguments"):
        bt.Backtest(strategy, data, commissions=lambda q: 0.0)
    
    # Correct signature
    bt.Backtest(strategy, data, commissions=lambda q, p: max(1, abs(q) * 0.01))

def test_valid_commission_variations():
    """Accept various valid commission signatures."""
    strategy = bt.Strategy("test", [])
    data = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2020", periods=2))
    
    # Standard
    bt.Backtest(strategy, data, commissions=lambda q, p: 0.01 * abs(q))
    
    # With defaults
    bt.Backtest(strategy, data, commissions=lambda q, p=1.0: 0.01 * abs(q))
    
    # With *args
    def fn(q, p, **kwargs):
        return 0.01 * abs(q)
    bt.Backtest(strategy, data, commissions=fn)
```

### Step 3: Verify

Run tests and lint:
```bash
python3 -m pytest tests/test_backtest.py -q
python3 -m ruff check bt
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Invalid type | `.venv/bin/python -c "import bt, pandas as pd; bt.Backtest(bt.Strategy('t',[]), pd.DataFrame({'A':[1]}), commissions='bad')"` | `TypeError: commissions must be a callable` |
| Invalid sig | `.venv/bin/python -c "import bt, pandas as pd; bt.Backtest(bt.Strategy('t',[]), pd.DataFrame({'A':[1]}), commissions=lambda q: 0)"` | `TypeError: at least 2 arguments` |
| Valid | `.venv/bin/python -c "import bt, pandas as pd; bt.Backtest(bt.Strategy('t',[]), pd.DataFrame({'A':[1]}), commissions=lambda q,p: 0.01*abs(q))"` | No error |
| Test | `python3 -m pytest tests/test_backtest.py -q` | All pass |
| Full test | `python3 -m pytest tests/ -q` | 182+ passed (new tests included) |

## Test Plan

Add 3 new test functions:
1. `test_invalid_commission_type` — ensures non-callable rejected
2. `test_invalid_commission_signature` — ensures wrong arity rejected
3. `test_valid_commission_variations` — ensures valid signatures accepted

## Maintenance Note

- This validation runs at Backtest construction time — cheap, fails fast.
- If users need more complex commission logic (e.g., tiered fees), they should wrap their function: `lambda q, p, **kw: ...` which is accepted by the validation.
- The `inspect` module is in stdlib — no new dependencies.

## Escape Hatches

- **If `inspect.signature` behavior varies across Python versions**: Add a `try/except` around the inspection and fall back to a lenient check (`hasattr(commissions, '__call__')`) on older Pythons.
- **If backward compatibility is a concern**: Make the validation a warning instead of an error, with a config flag to promote to error later.

## Evidence References

- `bt/backtest.py:162-201` — Backtest constructor
- `bt/core.py:1073-1082` — set_commissions method
- `tests/test_backtest.py` — existing test patterns to follow