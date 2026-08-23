# Plan 07: Plugin/Extension System for Custom Algos (Design Plan)

## Finding

**DIR-01**: Users currently extend bt by copying `examples/pairs_trading.py` patterns — defining custom Algo subclasses inline in their scripts. There is no official extension mechanism. This leads to:
- Duplicated code across projects
- Difficulty sharing custom algos
- No namespace management for custom algos

Evidence:
- `examples/pairs_trading.py:9-66` — Custom `PairsSignal`, `SetupPairsTrades`, `SizePairsTrades`, `WeighPair`, `PriceCompare`, `ClosePositions` algos defined inline
- No plugin registry in `bt.algos`
- No import mechanism for external algos

## Context

The current algo execution is hardcoded:
```python
# bt/core.py:2030-2050
class AlgoStack(Algo):
    def __init__(self, *algos):
        self.algos = algos
    
    def __call__(self, target):
        for algo in self.algos:
            if not algo(target):
                return False
        return True
```

To support plugins, we need:
1. A registry to discover and load custom algo classes
2. A convention for naming plugins
3. An optional import hook or entry point system

## Design Options

### Option A: Entry Points (setuptools)

```python
# User's plugin package
from setuptools import setup

setup(
    name="my-bt-plugins",
    entry_points={
        "bt.algos": [
            "my_algos = my_plugins.algos",
        ]
    }
)
```

```python
# bt/registry.py
import pkg_resources

def discover_algos():
    """Discover algos from installed plugins."""
    algos = {}
    for ep in pkg_resources.iter_entry_points("bt.algos"):
        module = ep.load()
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, Algo):
                algos[name] = obj
    return algos
```

**Pros**: Standard Python packaging, well-understood  
**Cons**: Requires plugin packages to be installed, harder for quick testing

### Option B: Path-based Discovery

```python
# bt/registry.py
import os
import sys

def discover_algos(plugin_paths=None):
    """Discover algos from user-specified paths."""
    algos = {}
    if plugin_paths:
        for path in plugin_paths:
            if path not in sys.path:
                sys.path.insert(0, path)
            try:
                module = importlib.import_module(os.path.basename(path))
                for name in dir(module):
                    obj = getattr(module, name)
                    if isinstance(obj, type) and issubclass(obj, Algo):
                        algos[name] = obj
            except ImportError:
                pass
    return algos
```

**Pros**: Simple, no packaging required  
**Cons**: Path management, less standard

### Option C: Hybrid (Recommended)

Combine both approaches with a configuration file.

## Proposed Implementation

### Step 1: Create `bt/registry.py`

```python
"""Plugin registry for custom algos and node types."""

import importlib
import os
import sys
from typing import Dict, List, Type, Optional

from .core import Algo, Node

# Global registry
_REGISTRY: Dict[str, Type] = {}

def register(name: str, cls: Type) -> None:
    """Register a class in the global registry."""
    _REGISTRY[name] = cls

def discover(path: Optional[str] = None) -> Dict[str, Type]:
    """
    Discover and register algos from a path.
    
    Args:
        path: Directory or file to scan. If None, scans BT_PLUGIN_PATH env var.
    
    Returns:
        Dict of class_name -> class
    """
    plugins_dir = path or os.environ.get("BT_PLUGIN_PATH")
    if not plugins_dir:
        return {}
    
    discovered = {}
    
    if os.path.isdir(plugins_dir):
        for filename in os.listdir(plugins_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                module_path = os.path.join(plugins_dir, filename)
                
                # Import the module
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Register public classes
                for name in dir(module):
                    if name.startswith("_"):
                        continue
                    obj = getattr(module, name)
                    if isinstance(obj, type) and (
                        issubclass(obj, Algo) or issubclass(obj, Node)
                    ):
                        discovered[name] = obj
                        register(name, obj)
    
    return discovered

def get_registered() -> Dict[str, Type]:
    """Return all registered classes."""
    return _REGISTRY.copy()

def get_algo(name: str) -> Optional[Type[Algo]]:
    """Get a registered algo by name."""
    cls = _REGISTRY.get(name)
    if cls and issubclass(cls, Algo):
        return cls
    return None

def get_node_type(name: str) -> Optional[Type[Node]]:
    """Get a registered node type by name."""
    cls = _REGISTRY.get(name)
    if cls and issubclass(cls, Node):
        return cls
    return None
```

### Step 2: Integrate with existing discovery

Update `bt/algos.py` or create `bt/discovery.py`:
```python
def all_algos() -> List[type]:
    """Return all built-in and plugin algos."""
    import bt.algos as builtin
    algos = [
        getattr(builtin, name) 
        for name in dir(builtin)
        if isinstance(getattr(builtin, name), type) 
        and issubclass(getattr(builtin, name), Algo)
    ]
    # Add plugins
    algos.extend(discover().values())
    return algos
```

### Step 3: Add CLI support

```python
# bt/cli.py
import click

@click.group()
def cli():
    pass

@cli.command()
@click.option("--path", help="Path to plugin directory")
def plugins(path):
    """Discover and list available plugins."""
    from .registry import discover, get_registered
    discovered = discover(path)
    for name, cls in get_registered().items():
        click.echo(f"{name}: {cls.__module__}")
```

### Step 4: Update GUI integration (for bt-gui)

The bt-gui's algo registry should query both built-in and plugin algos:
```python
# bt_gui/services/algo_registry.py
from bt.registry import all_algos, discover

def discover_all_algos():
    # Built-in
    algos = list_all_builtins()
    # Plugins
    plugin_path = os.environ.get("BT_PLUGIN_PATH")
    if plugin_path:
        algos.extend(discover(plugin_path).values())
    return algos
```

## Verification

```bash
# Test basic discovery
python -c "from bt.registry import discover; print(discover())"

# Test with plugin
BT_PLUGIN_PATH=/path/to/plugins python -c "from bt.registry import discover; print(discover())"
```

## Test Plan

Add `tests/test_registry.py`:
```python
def test_register_and_lookup():
    """Test basic registration and lookup."""
    from bt.registry import register, get_algo
    from bt.core import Algo
    
    class TestAlgo(Algo):
        def __call__(self, target):
            return True
    
    register("TestAlgo", TestAlgo)
    assert get_algo("TestAlgo") is TestAlgo

def test_discover_from_path():
    """Test discovering algos from a plugin path."""
    # Create temp plugin directory with a test algo
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = os.path.join(tmpdir, "test_plugin.py")
        with open(plugin_file, "w") as f:
            f.write("""
from bt.core import Algo
class MyCustomAlgo(Algo):
    def __call__(self, target):
        return True
""")
        from bt.registry import discover
        algos = discover(tmpdir)
        assert "MyCustomAlgo" in algos
```

## Maintenance Note

- **Naming conflicts**: If two plugins define the same class name, the last one wins. Document this behavior.
- **Plugin lifecycle**: Registered algos persist for the lifetime of the Python process. This is fine for CLI use but may need cleanup for long-running services.
- **Security**: Plugin code runs in the same process. Only load plugins from trusted paths.

## Escape Hatches

- **If entry points are preferred**: Replace path-based discovery with `pkg_resources.iter_entry_points("bt.algos")`.
- **If plugins need to define new node types**: Extend `discover()` to also return `Node` subclasses (already supported in the design).
- **If the registry becomes a bottleneck**: Switch to lazy loading — only import plugins when requested.

## Evidence References

- `examples/pairs_trading.py:9-66` — Custom algo patterns users currently replicate
- `bt/core.py:2030-2050` — AlgoStack execution (extension point)
- `bt/algos.py` — 185 symbols, all built-in algos (shows need for external extension)