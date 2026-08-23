# Plan 06: Strategy Serialization Format (Design Plan)

## Finding

**DIR-02**: Strategies are currently defined only as Python objects. There is no declarative/serializable format for strategies. This makes it impossible to:
- Share strategies between users
- Version strategies in git meaningfully
- Build a GUI editor (the user's primary use case for bt-gui)
- Reload strategies from disk

Evidence:
- `examples/pairs_trading.py` shows complex strategy construction in code
- No save/load mechanism exists in `bt` itself
- The `to_dot()` method on `Node` shows some serialization intent

## Context

A strategy in `bt` consists of:
1. A tree of nodes (Strategy → Strategy/Security → ...)
2. Each Strategy node has an `AlgoStack` (list of Algos)
3. Each Algo has a class name and constructor arguments
4. Each node has type-specific parameters (multiplier, fixed_income, etc.)

## Design Goals

1. **Human-readable**: YAML or JSON format
2. **Round-trip safe**: Serialize → deserialize → identical structure
3. **Extensible**: New node types and algos can be added without format changes
4. **GUI-friendly**: Easy for a GUI to construct and edit

## Proposed Format (YAML)

```yaml
name: "My Strategy"
root:
  name: "Portfolio"
  type: "Strategy"
  algos:
    - class: "RunMonthly"
      params:
        run_on_first_date: true
    - class: "SelectAll"
      params: {}
    - class: "WeighEqually"
      params: {}
    - class: "Rebalance"
      params: {}
  children:
    - name: "SPY"
      type: "Security"
      params: {}
    - name: "TLT"
      type: "Security"
      params: {}
    - name: "MomentumSub"
      type: "Strategy"
      params: {}
      algos:
        - class: "SelectMomentum"
          params:
            n: 3
            lookback: "3 months"
        - class: "WeighEqually"
          params: {}
      children:
        - name: "AAPL"
          type: "Security"
        - name: "GOOGL"
          type: "Security"
        - name: "MSFT"
          type: "Security"
```

## Implementation Steps

### Step 1: Define the schema

Create `bt/serializers.py` with:
```python
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

class AlgoDef(BaseModel):
    class_name: str
    params: Dict[str, Any] = Field(default_factory=dict)

class NodeDef(BaseModel):
    name: str
    type: Literal["Strategy", "Security", "FixedIncomeStrategy", 
                  "HedgeSecurity", "CouponPayingSecurity"]
    params: Dict[str, Any] = Field(default_factory=dict)
    algos: List[AlgoDef] = Field(default_factory=list)
    children: List["NodeDef"] = Field(default_factory=list)

class StrategyDef(BaseModel):
    name: str
    root: NodeDef
```

### Step 2: Implement serialize → YAML/JSON

```python
import yaml

def serialize_strategy(strategy: bt.Strategy) -> str:
    """Convert bt.Strategy to YAML string."""
    def node_to_def(node) -> NodeDef:
        params = {}
        if hasattr(node, 'multiplier'):
            params['multiplier'] = node.multiplier
        if hasattr(node, 'fixed_income'):
            params['fixed_income'] = node.fixed_income
        
        algos = []
        if isinstance(node, bt.Strategy) and hasattr(node, 'algos'):
            for algo in node.algos:
                algos.append(AlgoDef(
                    class_name=type(algo).__name__,
                    params={k: v for k, v in getattr(algo, '__dict__', {}).items() 
                            if not k.startswith('_')}
                ))
        
        children = [node_to_def(c) for c in node.children.values()]
        
        return NodeDef(
            name=node.name,
            type=type(node).__name__,
            params=params,
            algos=algos,
            children=children,
        )
    
    schema = StrategyDef(name=strategy.name, root=node_to_def(strategy))
    return yaml.dump(schema.model_dump(), default_flow_style=False)
```

### Step 3: Implement deserialize → bt.Strategy

```python
def deserialize_strategy(yaml_str: str) -> bt.Strategy:
    """Convert YAML string to bt.Strategy."""
    import importlib
    import inspect
    
    schema = StrategyDef.model_validate(yaml.safe_load(yaml_str))
    
    # Map string names to actual classes
    algo_classes = {
        'RunOnce': bt.algos.RunOnce,
        'RunMonthly': bt.algos.RunMonthly,
        'SelectAll': bt.algos.SelectAll,
        'WeighEquably': bt.algos.WeighEqually,
        'Rebalance': bt.algos.Rebalance,
        # ... add all bt.algos classes
    }
    
    def build_node(defn: NodeDef) -> bt.Node:
        # Create node based on type
        node_map = {
            'Strategy': bt.Strategy,
            'Security': bt.Security,
            'FixedIncomeStrategy': bt.FixedIncomeStrategy,
            'HedgeSecurity': bt.HedgeSecurity,
            'CouponPayingSecurity': bt.CouponPayingSecurity,
        }
        node_class = node_map[defn.type]
        
        node = node_class(name=defn.name)
        
        # Set params
        if 'multiplier' in defn.params:
            node.multiplier = defn.params['multiplier']
        if 'fixed_income' in defn.params:
            node._fixed_income = defn.params['fixed_income']
        
        # Build algos
        if defn.algos:
            algos = []
            for algo_def in defn.algos:
                algo_cls = algo_classes.get(algo_def.class_name)
                if algo_cls is None:
                    raise ValueError(f"Unknown algo: {algo_def.class_name}")
                algos.append(algo_cls(**algo_def.params))
            node.algos = algos
        
        # Build children recursively
        for child_def in defn.children:
            build_node(child_def)  # Auto-adds to node.children
        
        return node
    
    return build_node(schema.root)
```

### Step 4: Integration tests

Add `tests/test_serialization.py`:
```python
def test_roundtrip_simple():
    """Strategy → YAML → Strategy should produce equivalent structure."""
    original = bt.Strategy("test", [
        bt.algos.RunMonthly(),
        bt.algos.SelectAll(),
        bt.algos.WeighEqually(),
        bt.algos.Rebalance(),
    ], children=["SPY", "TLT"])
    
    yaml_str = serialize_strategy(original)
    restored = deserialize_strategy(yaml_str)
    
    assert restored.name == original.name
    assert len(restored.children) == 2
    assert list(restored.children.keys()) == ["SPY", "TLT"]
    assert len(restored.algos) == 4

def test_nested_strategy():
    """Test tree with nested sub-strategies."""
    # Build complex strategy...
    # Serialize and deserialize...
    # Assert structure preserved
    pass
```

### Step 5: CLI commands (optional v2)

Add to `bt` CLI:
```python
# bt serialize strategy.bt --format yaml
# bt deserialize strategy.yaml --name "Restored Strategy"
```

## Verification Commands

| Step | Command | Expected |
|------|---------|----------|
| Import | `python -c "from bt.serializers import serialize_strategy, deserialize_strategy"` | No error |
| Roundtrip | `python -m pytest tests/test_serialization.py -q` | All pass |
| CLI | `python -m bt.serialize --help` | Shows help (if implemented) |

## Test Plan

1. Simple strategy (1 level) — serialize + deserialize + compare
2. Nested strategy (2+ levels) — same
3. Strategy with params (weights, lookback, etc.) — same
4. Edge cases: empty children, no algos, single security

## Maintenance Note

- **Versioning**: Add a `version` field to the schema for future format changes.
- **Extensibility**: The `algo_classes` dict should be extensible — allow plugins to register their own algos.
- **Integration with GUI**: This serialization format is what bt-gui will use to save/load strategies.

## Escape Hatches

- **If Pydantic is too heavy**: Use plain dataclasses instead.
- **If round-trip fails for complex algos**: Start with serialization of simple strategies only, document limitations.
- **If users prefer JSON over YAML**: Support both formats; YAML is more readable for humans.

## Evidence References

- `examples/pairs_trading.py` — Complex strategy example (good test case)
- `bt/core.py:320-330` — Existing `to_dot()` shows serialization intent
- User requirement: GUI needs to save/load strategies