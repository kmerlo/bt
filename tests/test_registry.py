from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


def test_get_builtin_algo():
    from bt.registry import get_algo
    from bt.algos import RunMonthly

    assert get_algo("RunMonthly") is RunMonthly
    assert get_algo("NonExistentAlgo") is None


def test_get_builtin_node_type():
    from bt.registry import get_node_type
    from bt.core import Strategy, Security

    assert get_node_type("Strategy") is Strategy
    assert get_node_type("Security") is Security
    assert get_node_type("NonExistentNode") is None


def test_register_and_lookup():
    from bt.registry import register, get_algo, unregister
    from bt.core import Algo

    class TestAlgo(Algo):
        def __call__(self, target):
            return True

    register("TestAlgo", TestAlgo)
    assert get_algo("TestAlgo") is TestAlgo

    unregister("TestAlgo")
    assert get_algo("TestAlgo") is None


def test_discover_from_path():
    from bt.registry import discover

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = os.path.join(tmpdir, "test_plugin.py")
        with open(plugin_file, "w") as f:
            f.write(
                "from bt.core import Algo\n"
                "class MyCustomAlgo(Algo):\n"
                "    def __call__(self, target):\n"
                "        return True\n"
            )
        algos = discover(tmpdir)
        assert "MyCustomAlgo" in algos

        # Cleaning up the registry for other tests
        from bt.registry import unregister

        unregister("MyCustomAlgo")


def test_discover_ignores_private_files():
    from bt.registry import discover

    with tempfile.TemporaryDirectory() as tmpdir:
        # Private file should be ignored
        private = os.path.join(tmpdir, "_private.py")
        with open(private, "w") as f:
            f.write("from bt.core import Algo\n\nclass Hidden(Algo):\n" "    def __call__(self, t):\n" "        return True\n")
        algos = discover(tmpdir)
        assert "Hidden" not in algos
        from bt.registry import unregister

        unregister("Hidden")


def test_all_algos_includes_builtins():
    from bt.registry import all_algos

    algos = all_algos()
    assert "RunMonthly" in algos
    assert "SelectAll" in algos
    assert "Rebalance" in algos


def test_all_node_types_includes_builtins():
    from bt.registry import all_node_types

    nodes = all_node_types()
    assert "Strategy" in nodes
    assert "Security" in nodes
    assert "FixedIncomeStrategy" in nodes
