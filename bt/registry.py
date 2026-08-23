"""Plugin registry for custom algos and node types.

Users can place .py files in a directory and set the ``BT_PLUGIN_PATH``
environment variable (or pass a path explicitly) to make those algos
available alongside the built-in ones.

Example plugin::

    # my_plugins/my_algo.py
    from bt.core import Algo

    class MyCustomAlgo(Algo):
        def __call__(self, target):
            target.temp['selected'] = list(target.universe.columns)
            return True

Then run with::

    BT_PLUGIN_PATH=/path/to/plugins python my_backtest.py
"""

from __future__ import annotations

import importlib.util
import os
import sys

from bt.core import Algo, Node

_REGISTRY: dict[str, type] = {}
_populated = False


def _populate_builtin() -> None:
    """Seed the registry with all built-in algos and node types."""
    global _populated
    if _populated:
        return
    _populated = True
    import bt.algos as builtin

    for name, cls in vars(builtin).items():
        if isinstance(cls, type) and issubclass(cls, Algo):
            _REGISTRY[name] = cls

    from bt.core import (
        CouponPayingHedgeSecurity,
        CouponPayingSecurity,
        FixedIncomeSecurity,
        FixedIncomeStrategy,
        HedgeSecurity,
        Security,
        Strategy,
    )

    for _name, _cls in {
        "Strategy": Strategy,
        "FixedIncomeStrategy": FixedIncomeStrategy,
        "Security": Security,
        "FixedIncomeSecurity": FixedIncomeSecurity,
        "HedgeSecurity": HedgeSecurity,
        "CouponPayingSecurity": CouponPayingSecurity,
        "CouponPayingHedgeSecurity": CouponPayingHedgeSecurity,
    }.items():
        if _name not in _REGISTRY:
            _REGISTRY[_name] = _cls


def register(name: str, cls: type) -> None:
    """Register a class in the global registry."""
    if name not in _REGISTRY or _REGISTRY[name] is not cls:
        _REGISTRY[name] = cls


def unregister(name: str) -> None:
    """Remove a class from the registry."""
    _REGISTRY.pop(name, None)


def get_registered() -> dict[str, type]:
    """Return a copy of the global registry."""
    _populate_builtin()
    return dict(_REGISTRY)


def get_algo(name: str) -> type[Algo] | None:
    """Get a registered algo by name, or None if not found."""
    _populate_builtin()
    cls = _REGISTRY.get(name)
    if cls is not None and issubclass(cls, Algo):
        return cls  # type: ignore[return-value]
    return None


def get_node_type(name: str) -> type[Node] | None:
    """Get a registered node type by name, or None if not found."""
    _populate_builtin()
    cls = _REGISTRY.get(name)
    if cls is not None and issubclass(cls, Node):
        return cls  # type: ignore[return-value]
    return None


def discover(path: str | None = None) -> dict[str, type]:
    """
    Scan a directory for plugin .py files and register any Algo/Node
    subclasses found.

    Parameters
    ----------
    path : str or None
        Directory containing plugin .py files.  If None, falls back to
        the ``BT_PLUGIN_PATH`` environment variable.

    Returns
    -------
    dict
        Mapping of class name → class for everything newly discovered.
    """
    plugins_dir = path or os.environ.get("BT_PLUGIN_PATH")
    if not plugins_dir or not os.path.isdir(plugins_dir):
        return {}

    discovered: dict[str, type] = {}

    for filename in sorted(os.listdir(plugins_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = filename[:-3]
        module_path = os.path.join(plugins_dir, filename)

        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except OSError as exc:
            sys.stderr.write(f"bt.registry: failed to load {module_path}: {exc}\n")
            continue
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"bt.registry: failed to load {module_path}: {exc}\n")
            continue

        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if not isinstance(obj, type):
                continue
            try:
                is_algo = issubclass(obj, Algo)
            except TypeError:
                is_algo = False
            try:
                is_node = issubclass(obj, Node)
            except TypeError:
                is_node = False
            if is_algo or is_node:
                register(name, obj)
                discovered[name] = obj

    return discovered


def all_algos() -> dict[str, type]:
    """Return built-in + plugin algos merged into a single registry."""
    _populate_builtin()
    return {k: v for k, v in _REGISTRY.items() if issubclass(v, Algo)}


def all_node_types() -> dict[str, type]:
    """Return built-in + plugin node types merged into a single registry."""
    _populate_builtin()
    return {k: v for k, v in _REGISTRY.items() if issubclass(v, Node)}
