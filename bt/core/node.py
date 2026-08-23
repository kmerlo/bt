"""
Tree node base class.
"""

from __future__ import annotations

from copy import deepcopy

import cython as cy

PAR = 100.0
TOL = 1e-16


@cy.locals(x=cy.double)
def is_zero(x):
    """
    Test for zero that is robust against floating point precision errors
    """
    return abs(x) < TOL


class Node:
    """
    The Node is the main building block in bt's tree structure design.
    Both StrategyBase and SecurityBase inherit Node. It contains the
    core functionality of a tree node.

    Args:
        * name (str): The Node name
        * parent (Node): The parent Node
        * children (dict, list): A collection of children. If dict,
          the format is {name: child}, if list then list of children.
          Children can be any type of Node or str.
          String values correspond to children which will be lazily created
          with that name when needed.

    Attributes:
        * name (str): Node name
        * parent (Node): Node parent
        * root (Node): Root node of the tree (topmost node)
        * children (dict): Node's children
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Node is stale and need
          updating
        * prices (TimeSeries): Prices of the Node. Prices for a security will
          be the security's price, for a strategy it will be an index that
          reflects the value of the strategy over time.
        * price (float): last price
        * value (float): last value
        * notional_value (float): last notional value. Notional value is used
          when fixed_income=True. It is always positive for strategies, but
          is signed for securities (and typically set to either market value,
          position, or zero).
        * weight
        * full_name (str): Name including parents' names
        * members (list): Current Node + node's children
        * fixed_income (bool): Whether the node corresponds to a fixed income
          component, which would use notional-weighting instead of market
          value weighing. See also :class:`FixedIncomeStrategy <bt.core.FixedIncomeStrategy>`
          for more details.
    """

    _capital = cy.declare(cy.double)
    _price = cy.declare(cy.double)
    _value = cy.declare(cy.double)
    _notl_value = cy.declare(cy.double)
    _weight = cy.declare(cy.double)
    _issec = cy.declare(cy.bint)
    _has_strat_children = cy.declare(cy.bint)
    _fixed_income = cy.declare(cy.bint)
    _bidoffer_set = cy.declare(cy.bint)
    _bidoffer_paid = cy.declare(cy.double)

    def __init__(self, name, parent=None, children=None):
        self.name = name

        # children helpers
        self.children = {}
        self._lazy_children = {}
        self._universe_tickers = []
        self._childrenv = []  # Shortcut to self.children.values()
        self._original_children_are_present = (children is not None) and (len(children) >= 1)

        # strategy children helpers
        self._has_strat_children = False
        self._strat_children = []

        if parent is None:
            self.parent = self
            self.root = self
            # by default all positions are integer
            self.integer_positions = True
        else:
            self.parent = parent
            parent._add_children([self], dc=False)

        self._add_children(children, dc=True)

        # set default value for now
        self.now = 0
        # make sure root has stale flag
        # used to avoid unnecessary update
        # sometimes we change values in the tree and we know that we will need
        # to update if another node tries to access a given value (say weight).
        # This avoid calling the update until it is actually needed.
        self.root.stale = False

        # helper vars
        self._price = 0
        self._value = 0
        self._notl_value = 0
        self._weight = 0
        self._capital = 0

        # is security flag - used to avoid updating 0 pos securities
        self._issec = False

        # fixed income flag - used to turn on notional weighing
        self._fixed_income = False
        # flag for whether to do bid/offer accounting
        self._bidoffer_set = False
        self._bidoffer_paid = 0

    @property
    def data(self):
        if getattr(self, "_data_ready", False):
            self._sync_data()
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    def _sync_data(self):
        pass

    def __getitem__(self, key):
        return self.children[key]

    def _add_children(self, children, dc):
        """
        Add the collection of children to the current node, where
        children is either an iterable of children objects/strings, or
        a dictionary

        Args:
            dc (bool): Whether or not to deepcopy nodes before adding them.
        """
        from .security import Security

        # if at least 1 children is specified
        if children is not None:
            if isinstance(children, dict):
                # Preserve the names from the dictionary by renaming the nodes
                tmp = []
                for name, c in children.items():
                    if isinstance(c, str):
                        tmp.append(name)
                    else:
                        if dc:
                            c = deepcopy(c)
                        c.name = name
                        tmp.append(c)
                children = tmp

            for c in children:
                if dc:  # deepcopy object for possible later reuse
                    c = deepcopy(c)

                if isinstance(c, str):
                    if c in self._universe_tickers:
                        raise ValueError(f"Child {c} already exists")

                    # Create default security with lazy_add
                    c = Security(c, lazy_add=True)

                if getattr(c, "lazy_add", False):
                    self._lazy_children[c.name] = c
                else:
                    if c.name in self.children:
                        raise ValueError(f"Child {c} already exists")

                    c.parent = self
                    c._set_root(self.root)
                    c.use_integer_positions(self.integer_positions)

                    self.children[c.name] = c
                    self._childrenv.append(c)

                # if strategy, turn on flag and add name to list
                # strategy children have special treatment
                from .strategy import StrategyBase

                if isinstance(c, StrategyBase):
                    self._has_strat_children = True
                    self._strat_children.append(c.name)
                # if not strategy, then we will want to add this to
                # universe_tickers to filter on setup
                elif c.name not in self._universe_tickers:
                    self._universe_tickers.append(c.name)

    def _set_root(self, root):
        self.root = root
        for c in self._childrenv:
            c._set_root(root)

    def use_integer_positions(self, integer_positions):
        """
        Set indicator to use (or not) integer positions for a given strategy or
        security.

        By default all positions in number of stocks should be integer.
        However this may lead to unexpected results when working with adjusted
        prices of stocks. Because of series of reverse splits of stocks, the
        adjusted prices back in time might be high. Thus rounding of desired
        amount of stocks to buy may lead to having 0, and thus ignoring this
        stock from backtesting.
        """
        self.integer_positions = integer_positions
        for c in self._childrenv:
            c.use_integer_positions(integer_positions)

    @property
    def fixed_income(self):
        """
        Whether the node is a fixed income node (using notional weighting).
        """
        return self._fixed_income

    @property
    def prices(self):
        """
        A TimeSeries of the Node's price.
        """
        # can optimize depending on type -
        # securities don't need to check stale to
        # return latest prices, whereas strategies do...
        raise NotImplementedError()

    @property
    def price(self):
        """
        Current price of the Node
        """
        # can optimize depending on type -
        # securities don't need to check stale to
        # return latest prices, whereas strategies do...
        raise NotImplementedError()

    @property
    def value(self):
        """
        Current value of the Node
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._value

    @property
    def notional_value(self):
        """
        Current notional value of the Node
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._notl_value

    @property
    def weight(self):
        """
        Current weight of the Node (with respect to the parent).
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._weight

    def setup(self, universe, **kwargs):
        """
        Setup method used to initialize a Node with a universe, and potentially other information.
        """
        raise NotImplementedError()

    def update(self, date, data=None, inow=None):
        """
        Update Node with latest date, and optionally some data.
        """
        raise NotImplementedError()

    def adjust(self, amount, update=True, flow=True, fee=0.0):
        """
        Adjust Node value by amount.
        """
        raise NotImplementedError()

    def allocate(self, amount, update=True):
        """
        Allocate capital to Node.
        """
        raise NotImplementedError()

    @property
    def members(self):
        """
        Node members. Members include current node as well as Node's
        children.
        """
        res = [self]
        for c in list(self.children.values()):
            res.extend(c.members)
        return res

    @property
    def full_name(self):
        if self.parent == self:
            return self.name
        else:
            return f"{self.parent.full_name}>{self.name}"

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.full_name}>"

    def to_dot(self, root=True):
        """
        Represent the node structure in DOT format.
        """
        name = lambda x: x.name or repr(self)
        edges = "\n".join(f'\t"{name(self)}" -> "{name(c)}"' for c in self.children.values())
        below = "\n".join(c.to_dot(False) for c in self.children.values())
        body = f"{edges}\n{below}".rstrip()
        if root:
            return f"digraph {{\n{body}\n}}"
        return body
