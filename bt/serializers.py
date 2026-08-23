"""
Strategy serialization — convert bt.Strategy trees to/from JSON dicts.

Usage::

    import bt
    from bt.serializers import serialize, deserialize, list_algos

    # Serialize a strategy to JSON
    tree = serialize(strategy)
    json_str = json.dumps(tree, indent=2)

    # Deserialize back to a bt.Strategy
    tree = json.loads(json_str)
    restored = deserialize(tree)

    # List all serializable algo class names
    print(list_algos())
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from bt import algos
from bt.core import (
    Algo,
    AlgoStack,
    CouponPayingHedgeSecurity,
    CouponPayingSecurity,
    FixedIncomeSecurity,
    FixedIncomeStrategy,
    HedgeSecurity,
    Node,
    Security,
    Strategy,
)
from bt.registry import all_algos

# Mapping from class string to Algo class — built-in + plugin algos
ALGO_CLASS_MAP: dict[str, type] = all_algos()

# Mapping from type string to Python class
NODE_CLASS_MAP: dict[str, type] = {
    "Strategy": Strategy,
    "FixedIncomeStrategy": FixedIncomeStrategy,
    "Security": Security,
    "FixedIncomeSecurity": FixedIncomeSecurity,
    "HedgeSecurity": HedgeSecurity,
    "CouponPayingSecurity": CouponPayingSecurity,
    "CouponPayingHedgeSecurity": CouponPayingHedgeSecurity,
}

# Special constructors for AlgoStack subclasses that do not store
# their init params as instance attributes.  Maps class name ->
# callable(inner_algos, params) -> algo_instance.
_ALGO_RECONSTRUCTORS: dict[str, Callable[[list[Algo], dict[str, Any]], Algo]] = {
    "SelectMomentum": lambda inner, params: algos.SelectMomentum(
        n=params.get("n", 3),
        lookback=params.get("lookback", "12 months"),
        lag=params.get("lag", "1 day"),
        sort_descending=params.get("sort_descending", True),
        all_or_none=params.get("all_or_none", False),
    ),
}


def list_algos() -> list[str]:
    """Return sorted list of serializable algo class names."""
    return sorted(ALGO_CLASS_MAP.keys())


def _to_json_safe(value: Any) -> Any:
    """Convert values to JSON-safe primitives."""
    if value is None:
        return None
    try:
        import pandas as pd

        if isinstance(value, pd.Timedelta):
            return str(value)
        if isinstance(value, pd.DateOffset):
            return str(value)
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
    except ImportError:
        pass
    return value


def _algo_params(algo: Algo) -> dict[str, Any]:
    """Extract init-time parameters from an algo instance."""
    sig = inspect.signature(algo.__class__.__init__)
    params: dict[str, Any] = {}
    for pname in sig.parameters:
        if pname in ("self", "args", "kwargs"):
            continue
        if hasattr(algo, pname):
            val = getattr(algo, pname)
            if not pname.startswith("_"):
                params[pname] = _to_json_safe(val)
    return params


def _algo_to_dict(algo: Algo) -> dict[str, Any]:
    """Serialize a single algo, handling AlgoStack subclasses recursively."""
    cls_name = algo.__class__.__name__
    if cls_name not in ALGO_CLASS_MAP:
        return {"class": cls_name, "params": {}, "__custom__": True}

    params = _algo_params(algo)
    result: dict[str, Any] = {"class": cls_name, "params": params}

    if isinstance(algo, AlgoStack):
        result["algos"] = [_algo_to_dict(a) for a in algo.algos]

    return result


def _all_children(node: Node) -> dict[str, Node]:
    """Return all children including lazy ones."""
    result = dict(node.children)
    if hasattr(node, "_lazy_children"):
        result.update(node._lazy_children)
    return result


def _node_to_dict(node: Node) -> dict[str, Any]:
    cls_name = node.__class__.__name__

    if isinstance(node, Strategy):
        return _strategy_to_dict(node, cls_name)

    params: dict[str, Any] = {}
    if hasattr(node, "multiplier") and node.multiplier != 1:  # type: ignore[attr-defined]
        params["multiplier"] = node.multiplier  # type: ignore[attr-defined]
    if hasattr(node, "lazy_add") and node.lazy_add:  # type: ignore[attr-defined]
        params["lazy_add"] = True

    children = _all_children(node)
    return {
        "name": node.name,
        "type": cls_name,
        "params": params,
        "children": [_node_to_dict(c) for c in children.values()],
    }


def _strategy_to_dict(strategy: Strategy, cls_name: str) -> dict[str, Any]:
    algos_dict = [_algo_to_dict(a) for a in strategy.stack.algos]
    children = _all_children(strategy)
    return {
        "name": strategy.name,
        "type": cls_name,
        "params": {},
        "algos": algos_dict,
        "children": [_node_to_dict(c) for c in children.values()],
    }


def deserialize(data: dict[str, Any]) -> Strategy:
    """
    Deserialize a dict produced by :func:`serialize` back into a
    :class:`bt.Strategy`.

    Raises
    ------
    ValueError
        If an unknown node type or algo class name is encountered.
    """
    root = _dict_to_node(data["tree"])
    return root  # type: ignore[return-value]


def serialize(strategy: Strategy) -> dict[str, Any]:
    """
    Serialize a bt.Strategy tree to a plain dict.

    Returns a dict with keys ``name`` and ``tree`` suitable for JSON
    serialization. Custom algo classes (not in ``bt.algos``) are skipped
    with a warning and replaced by a ``"__custom__": true`` marker so that
    known structure is still preserved.
    """
    return {"name": strategy.name, "tree": _node_to_dict(strategy)}


def _dict_to_node(d: dict[str, Any]) -> Node:
    cls_name = d["type"]
    params = d.get("params", {}).copy()
    params["name"] = d["name"]
    children_defs = d.get("children", [])
    algos_defs = d.get("algos", [])

    if cls_name not in NODE_CLASS_MAP:
        raise ValueError(f"Unknown node type: {cls_name!r}")

    node_cls = NODE_CLASS_MAP[cls_name]

    if issubclass(node_cls, Strategy):
        return _build_strategy(d, node_cls, params, children_defs, algos_defs)

    node = NODE_CLASS_MAP[cls_name](**params)  # type: ignore[assignment]
    for child_def in children_defs:
        child = _dict_to_node(child_def)
        if child.parent is not node:
            node.children[child.name] = child
            child.parent = node
    return node  # type: ignore[return-value]


def _build_algo(algo_def: dict[str, Any]) -> Algo:
    """Deserialize a single algo definition, handling nested AlgoStacks."""
    cls_name = algo_def["class"]
    params = algo_def.get("params", {})
    nested_defs = algo_def.get("algos", [])

    if "__custom__" in algo_def:
        raise ValueError(f"Cannot deserialize custom algo {cls_name!r}. Only bt.algos classes are supported.")
    if cls_name not in ALGO_CLASS_MAP:
        raise ValueError(f"Unknown algo class: {cls_name!r}")

    algo_cls = ALGO_CLASS_MAP[cls_name]

    # Special constructor for AlgoStack subclasses that don't store params
    if cls_name in _ALGO_RECONSTRUCTORS:
        inner_algos = [_dict_to_algo(nd) for nd in nested_defs]
        return _ALGO_RECONSTRUCTORS[cls_name](inner_algos, params)  # type: ignore[return-value]

    # Standard algo: instantiate with params + nested algos as positional args
    if nested_defs:
        inner_algos = [_dict_to_algo(nd) for nd in nested_defs]
        return algo_cls(*inner_algos, **params)  # type: ignore[return-value]

    return algo_cls(**params)  # type: ignore[return-value]


def _dict_to_algo(d: dict[str, Any]) -> Algo:
    """Deserialize an algo definition dict into an algo instance."""
    return _build_algo(d)


def _build_strategy(
    d: dict[str, Any],
    cls: type,
    params: dict[str, Any],
    children_defs: list[dict[str, Any]],
    algos_defs: list[dict[str, Any]],
) -> Strategy:
    name = params.pop("name", d["name"])
    algos_list: list[Algo] = [_build_algo(a) for a in algos_defs]

    node = cls(name=name, algos=algos_list)  # type: ignore[call-arg]

    for child_def in children_defs:
        child = _dict_to_node(child_def)
        node.children[child.name] = child
        child.parent = node

    return node  # type: ignore[return-value]
