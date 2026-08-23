"""
Strategy node classes.
"""

from __future__ import annotations

from copy import deepcopy

import cython as cy
import numpy as np
import pandas as pd

from .node import PAR, Node, is_zero
from .security import Security, SecurityBase


class StrategyBase(Node):
    """
    Strategy Node. Used to define strategy logic within a tree.
    A Strategy's role is to allocate capital to it's children
    based on a function.

    Args:
        * name (str): Strategy name
        * children (dict, list): A collection of children. If dict,
          the format is {name: child}, if list then list of children.
          Children can be any type of Node or str.
          String values correspond to children which will be lazily created
          with that name when needed.
        * parent (Node): The parent Node

    Attributes:
        * name (str): Strategy name
        * parent (Strategy): Strategy parent
        * root (Strategy): Root node of the tree (topmost node)
        * children (dict): Strategy's children
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Strategy is stale and need
          updating
        * prices (TimeSeries): Prices of the Strategy - basically an index that
          reflects the value of the strategy over time.
        * outlays (DataFrame): Outlays for each SecurityBase child
        * price (float): last price
        * value (float): last value
        * notional_value (float): last notional value
        * weight (float): weight in parent
        * full_name (str): Name including parents' names
        * members (list): Current Strategy + strategy's children
        * securities (list): List of strategy children that are of type
          SecurityBase
        * commission_fn (fn(quantity, price)): A function used to determine the
          commission (transaction fee) amount. Could be used to model
          slippage (implementation shortfall). Note that often fees are
          symmetric for buy and sell and absolute value of quantity should
          be used for calculation.
        * capital (float): Capital amount in Strategy - cash
        * universe (DataFrame): Data universe available at the current time.
          Universe contains the data passed in when creating a Backtest. Use
          this data to determine strategy logic.

    """

    _net_flows = cy.declare(cy.double)
    _last_value = cy.declare(cy.double)
    _last_notl_value = cy.declare(cy.double)
    _last_price = cy.declare(cy.double)
    _last_fee = cy.declare(cy.double)
    _paper_trade = cy.declare(cy.bint)
    bankrupt = cy.declare(cy.bint)

    def __init__(self, name, children=None, parent=None):
        Node.__init__(self, name, children=children, parent=parent)
        self._weight = 1
        self._value = 0
        self._notl_value = 0
        self._price = PAR

        # helper vars
        self._net_flows = 0
        self._last_value = 0
        self._last_notl_value = 0
        self._last_price = PAR
        self._last_fee = 0

        self._last_chk: int | None = 0

        # default commission function
        self.commission_fn = self._dflt_comm_fn

        self._paper_trade = False
        self._positions = None
        self.bankrupt = False

    @property
    def price(self):
        """
        Current price.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._price

    @property
    def prices(self):
        """
        TimeSeries of prices.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._prices.loc[: self.now]

    @property
    def values(self):
        """
        TimeSeries of values.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._values.loc[: self.now]

    @property
    def notional_values(self):
        """
        TimeSeries of notional values.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._notl_values.loc[: self.now]

    @property
    def capital(self):
        """
        Current capital - amount of unallocated capital left in strategy.
        """
        # no stale check needed
        return self._capital

    @property
    def cash(self):
        """
        TimeSeries of unallocated capital.
        """
        # no stale check needed
        return self._cash

    @property
    def fees(self):
        """
        TimeSeries of fees.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._fees.loc[: self.now]

    @property
    def flows(self):
        """
        TimeSeries of flows.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._all_flows.loc[: self.now]

    @property
    def bidoffer_paid(self):
        """
        Bid/offer spread paid on transactions in the current step
        """
        if self._bidoffer_set:
            if self.root.stale:
                self.root.update(self.now, None)
            return self._bidoffer_paid
        else:
            raise RuntimeError('Bid/offer accounting not turned on: "bidoffer" argument not provided during setup')

    @property
    def bidoffers_paid(self):
        """
        TimeSeries of bid/offer spread paid on transactions in each step
        """
        if self._bidoffer_set:
            if self.root.stale:
                self.root.update(self.now, None)
            return self._bidoffers_paid.loc[: self.now]
        else:
            raise RuntimeError('Bid/offer accounting not turned on: "bidoffer" argument not provided during setup')

    @property
    def universe(self):
        """
        Data universe available at the current time.
        Universe contains the data passed in when creating a Backtest.
        Use this data to determine strategy logic.
        """
        # avoid windowing every time
        # if calling and on same date return
        # cached value
        if self.now == self._last_chk:
            return self._funiverse
        else:
            self._last_chk = self.now
            self._funiverse = self._universe.loc[: self.now]
            return self._funiverse

    @property
    def securities(self):
        """
        Returns a list of children that are of type SecurityBase
        """
        return [x for x in self.members if isinstance(x, SecurityBase)]

    @property
    def outlays(self):
        """
        Returns a DataFrame of outlays for each child SecurityBase
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        outlays = pd.DataFrame()
        for x in self.securities:
            if x.name in outlays.columns:
                outlays[x.name] += x.outlays
            else:
                outlays[x.name] = x.outlays
        return outlays

    @property
    def positions(self):
        """
        TimeSeries of positions.
        """
        # if accessing and stale - update first
        if self.root.stale:
            self.root.update(self.root.now, None)

        vals = pd.DataFrame()
        for x in self.members:
            if isinstance(x, SecurityBase):
                if x.name in vals.columns:
                    vals[x.name] += x.positions
                else:
                    vals[x.name] = x.positions
        self._positions = vals.fillna(0.0)
        return vals

    def setup(self, universe, **kwargs):
        """
        Setup strategy with universe. This will speed up future calculations
        and updates.
        """
        # save full universe in case we need it
        self._original_data = universe
        self._setup_kwargs = kwargs

        # Guard against fixed income children of regular
        # strategies as the "price" is just a reference
        # value and should not be used for capital allocation
        if self.fixed_income and not self.parent.fixed_income:
            raise ValueError(f"Cannot have fixed income strategy child ({self.name}) of non-fixed income strategy ({self.parent.name})")

        # determine if needs paper trading
        # and setup if so
        if self is not self.parent:
            self._paper_trade = True
            self._paper_amount = 1000000

            paper = deepcopy(self)
            paper.parent = paper
            paper.root = paper
            paper._paper_trade = False
            paper.setup(self._original_data, **kwargs)
            paper.adjust(self._paper_amount)
            self._paper = paper

        # setup universe
        funiverse = universe.copy()

        # filter only if the node has any children specified as input,
        # otherwise we use the full universe. If all children are strategies,
        # funiverse will be empty, to signal that no other ticker should be
        # used in addition to the strategies
        if self._original_children_are_present:
            # if we have universe_tickers defined, limit universe to
            # those tickers
            valid_filter = list(set(universe.columns).intersection(self._universe_tickers))

            funiverse = universe[valid_filter].copy()

            # if we have strat children, we will need to create their columns
            # in the new universe
            if self._has_strat_children:
                for c in self._strat_children:
                    funiverse[c] = np.nan

            # must create to avoid pandas warning
            funiverse = pd.DataFrame(funiverse)

        self._universe = funiverse
        # holds filtered universe
        self._funiverse = funiverse
        self._last_chk = None

        # We're not bankrupt yet
        self.bankrupt = False

        # setup internal data
        self.data = pd.DataFrame(
            index=funiverse.index,
            columns=["price", "value", "notional_value", "cash", "fees", "flows"],
            data=0.0,
        )

        self._prices = self.data["price"]
        self._values = self.data["value"]
        self._notl_values = self.data["notional_value"]
        self._cash = self.data["cash"]
        self._fees = self.data["fees"]
        self._all_flows = self.data["flows"]

        if "bidoffer" in kwargs:
            self._bidoffer_set = True
            self.data["bidoffer_paid"] = 0.0
            self._bidoffers_paid = self.data["bidoffer_paid"]

        # setup children as well - use original universe here - don't want to
        # pollute with potential strategy children in funiverse
        if self.children is not None:
            [c.setup(universe, **kwargs) for c in self._childrenv]

        self._data_ready = True

    def setup_from_parent(self, **kwargs):
        """
        Setup a strategy from the parent. Used when dynamically creating
        child strategies.

        Args:
            * kwargs: additional arguments that will be passed to setup
                (potentially overriding those from the parent)
        """
        all_kwargs = self.parent._setup_kwargs.copy()
        all_kwargs.update(kwargs)
        self.setup(self.parent._original_data, **all_kwargs)
        if self.name not in self.parent._universe:
            self.parent._universe[self.name] = np.nan

    def get_data(self, key):
        """
        Returns additional data that was passed to the setup function via kwargs,
        for use in the algos. This allows algos to reference data sources "by name",
        where the binding of the data to the name happens at Backtest creation
        time rather than at Strategy definition time, allowing the same strategies
        to be run against different data sets more easily.
        """
        return self._setup_kwargs[key]

    def _sync_data(self):
        self._data["price"] = self._prices
        self._data["value"] = self._values
        self._data["notional_value"] = self._notl_values
        self._data["cash"] = self._cash
        self._data["fees"] = self._fees
        self._data["flows"] = self._all_flows
        if self._bidoffer_set:
            self._data["bidoffer_paid"] = self._bidoffers_paid

    @cy.locals(
        newpt=cy.bint,
        val=cy.double,
        ret=cy.double,
        coupons=cy.double,
        notl_val=cy.double,
        bidoffer_paid=cy.double,
    )
    def update(self, date, data=None, inow=None):
        """
        Update strategy. Updates prices, values, weight, etc.
        """
        # resolve stale state
        self.root.stale = False

        # update helpers on date change
        # also set newpt flag
        newpt = False
        if self.now == 0:
            newpt = True
        elif date != self.now:
            self._net_flows = 0
            self._last_price = self._price
            self._last_value = self._value
            self._last_notl_value = self._notl_value
            self._last_fee = 0.0
            newpt = True

        # update now
        self.now = date
        if inow is None:
            if self.now == 0:
                inow = 0
            else:
                inow = self._data.index.get_loc(date)

        # update children if any and calculate value
        val = self._capital  # default if no children
        notl_val = 0.0  # Capital doesn't count towards notional value

        bidoffer_paid = 0.0
        coupons = 0
        if self.children:
            for c in self._childrenv:
                # Sweep up cash from the security nodes (from coupon payments, etc)
                if c._issec and newpt:
                    coupons += c._capital
                    c._capital = 0

                # avoid useless update call
                if c._issec and not c._needupdate:
                    continue

                c.update(date, data, inow)
                val += c.value
                # Strategies always have positive notional value
                notl_val += abs(c.notional_value)

                if self._bidoffer_set:
                    bidoffer_paid += c.bidoffer_paid

        self._capital += coupons
        val += coupons

        if self.root == self and (val < 0) and not self.bankrupt and not self.fixed_income and not is_zero(val):
            # Declare a bankruptcy
            self.bankrupt = True
            self.flatten()

        # update data if this value is different or
        # if now has changed - avoid all this if not since it
        # won't change
        if newpt or not is_zero(self._value - val) or not is_zero(self._notl_value - notl_val):
            self._value = val
            self._values.iloc[inow] = val

            self._notl_value = notl_val
            self._notl_values.iloc[inow] = notl_val

            if self._bidoffer_set:
                self._bidoffer_paid = bidoffer_paid
                self._bidoffers_paid.iloc[inow] = bidoffer_paid

            if self.fixed_income:
                # For notional weights, we compute additive return
                pnl = self._value - (self._last_value + self._net_flows)
                if not is_zero(self._last_notl_value):
                    ret = pnl / self._last_notl_value * PAR
                elif not is_zero(self._notl_value):
                    # This case happens when paying bid/offer or fees when building an initial position
                    ret = pnl / self._notl_value * PAR
                else:
                    if is_zero(pnl):
                        ret = 0
                    else:
                        raise ZeroDivisionError(
                            f"Could not update {self.name} on {self.now}. Last notional value "
                            f"was {self._last_notl_value} and pnl was {pnl}. Therefore, "
                            "we are dividing by zero to obtain the pnl "
                            "per unit notional for the period."
                        )

                self._price = self._last_price + ret
                self._prices.iloc[inow] = self._price

            else:
                bottom = self._last_value + self._net_flows
                if not is_zero(bottom):
                    ret = self._value / (self._last_value + self._net_flows) - 1
                else:
                    if is_zero(self._value):
                        ret = 0
                    elif self.parent == self and is_zero(self._capital) and is_zero(self._last_value) and is_zero(self._net_flows):
                        # Paper-trade root strategies can open their initial
                        # positions before their synthetic return series has a
                        # non-zero base. Treat that bootstrap step as a flat
                        # return and let the paper price drive performance.
                        ret = 0
                    else:
                        raise ZeroDivisionError(
                            f"Could not update {self.name} on {self.now}. Last value "
                            f"was {self._last_value} and net flows were {self._net_flows}. Current"
                            f"value is {self._value}. Therefore, "
                            "we are dividing by zero to obtain the return "
                            "for the period."
                        )

                self._price = self._last_price * (1 + ret)
                self._prices.iloc[inow] = self._price

        # update children weights
        if self.children:
            for c in self._childrenv:
                # avoid useless update call
                if c._issec and not c._needupdate:
                    continue

                if self.fixed_income:
                    if not is_zero(notl_val):
                        c._weight = c.notional_value / notl_val
                    else:
                        c._weight = 0.0
                else:
                    if not is_zero(val):
                        c._weight = c.value / val
                    else:
                        c._weight = 0.0

        # if we have strategy children, we will need to update them in universe
        if self._has_strat_children:
            for c in self._strat_children:
                # TODO: optimize ".loc" here as well
                self._universe.loc[date, c] = self.children[c].price

        # Cash should track the unallocated capital at the end of the day, so
        # we should update it every time we call "update".
        # Same for fees and flows
        self._cash.iloc[inow] = self._capital
        self._fees.iloc[inow] = self._last_fee
        self._all_flows.iloc[inow] = self._net_flows

        # update paper trade if necessary
        if self._paper_trade:
            if newpt:
                self._paper.update(date)
                self._paper.run()
                self._paper.update(date)
            # update price
            self._price = self._paper.price
            self._prices.iloc[inow] = self._price

    @cy.locals(amount=cy.double, update=cy.bint, flow=cy.bint, fees=cy.double)
    def adjust(self, amount, update=True, flow=True, fee=0.0):
        """
        Adjust capital - used to inject capital to a Strategy. This injection
        of capital will have no effect on the children.

        Args:
            * amount (float): Amount to adjust by.
            * update (bool): Force update?
            * flow (bool): Is this adjustment a flow? A flow will not have an
              impact on the performance (price index). Example of flows are
              simply capital injections (say a monthly contribution to a
              portfolio). This should not be reflected in the returns. A
              non-flow (flow=False) does impact performance. A good example
              of this is a commission, or a dividend.

        """
        # adjust capital
        self._capital += amount
        self._last_fee += fee

        # if flow - increment net_flows - this will not affect
        # performance. Commissions and other fees are not flows since
        # they have a performance impact
        if flow:
            self._net_flows += amount

        if update:
            # indicates that data is now stale and must
            # be updated before access
            self.root.stale = True

    @cy.locals(amount=cy.double, update=cy.bint)
    def allocate(self, amount, child=None, update=True):
        """
        Allocate capital to Strategy. By default, capital is allocated
        recursively down the children, proportionally to the children's
        weights.  If a child is specified, capital will be allocated
        to that specific child.

        Allocation also have a side-effect. They will deduct the same amount
        from the parent's "account" to offset the allocation. If there is
        remaining capital after allocation, it will remain in Strategy.

        Args:
            * amount (float): Amount to allocate.
            * child (str): If specified, allocation will be directed to child
              only. Specified by name.
            * update (bool): Force update.

        """
        # allocate to child
        if child is not None:
            self._create_child_if_needed(child)

            # allocate to child
            self.children[child].allocate(amount)
        # allocate to self
        else:
            # adjust parent's capital
            # no need to update now - avoids repetition
            if self.parent == self:
                self.parent.adjust(-amount, update=False, flow=True)
            else:
                # do NOT set as flow - parent will be another strategy
                # and therefore should not incur flow
                self.parent.adjust(-amount, update=False, flow=False)

            # adjust self's capital
            self.adjust(amount, update=False, flow=True)

            # push allocation down to children if any
            # use _weight to avoid triggering an update
            if self.children is not None:
                [c.allocate(amount * c._weight, update=False) for c in self._childrenv]

            # mark as stale if update requested
            if update:
                self.root.stale = True

    @cy.locals(q=cy.double, update=cy.bint)
    def transact(self, q, child=None, update=True):
        """
        Transact a notional amount q in the Strategy. By default, it is allocated
        recursively down the children, proportionally to the children's
        weights. Recursive allocation only works for fixed income strategies.
        If a child is specified, notional will be allocated
        to that specific child.

        Args:
            * q (float): Notional quantity to allocate.
            * child (str): If specified, allocation will be directed to child
              only. Specified by name.
            * update (bool): Force update.

        """
        # allocate to child
        if child is not None:
            self._create_child_if_needed(child)

            # allocate to child
            self.children[child].transact(q)
        # allocate to self
        else:
            # push allocation down to children if any
            # use _weight to avoid triggering an update
            if self.children is not None:
                [c.transact(q * c._weight, update=False) for c in self._childrenv]

            # mark as stale if update requested
            if update:
                self.root.stale = True

    @cy.locals(delta=cy.double, weight=cy.double, base=cy.double, update=cy.bint)
    def rebalance(self, weight, child, base=np.nan, update=True):
        """
        Rebalance a child to a given weight.

        This is a helper method to simplify code logic. This method is used
        when we want to see the weight of a particular child to a set amount.
        It is similar to allocate, but it calculates the appropriate allocation
        based on the current weight. For fixed income strategies, it uses
        transact to rebalance based on notional value instead of capital.

        Args:
            * weight (float): The target weight. Usually between -1.0 and 1.0.
            * child (str): child to allocate to - specified by name.
            * base (float): If specified, this is the base amount all weight
              delta calculations will be based off of. This is useful when we
              determine a set of weights and want to rebalance each child
              given these new weights. However, as we iterate through each
              child and call this method, the base (which is by default the
              current value) will change. Therefore, we can set this base to
              the original value before the iteration to ensure the proper
              allocations are made.
            * update (bool): Force update?

        """
        # if weight is 0 - we want to close child
        if is_zero(weight):
            if child in self.children:
                return self.close(child, update=update)
            else:
                return

        # if no base specified use self's value
        if np.isnan(base):
            if self.fixed_income:
                base = self.notional_value
            else:
                base = self.value

        # else make sure we have child
        self._create_child_if_needed(child)

        # allocate to child
        # figure out weight delta
        c = self.children[child]

        if self.fixed_income:
            # In fixed income strategies, the provided "base" value can be used
            # to upscale/downscale the notional_value of the strategy, whereas
            # in normal strategies the total capital is fixed. Thus, when
            # rebalancing, we must take care to account for differences between
            # previous notional value and passed base value. Note that for
            # updating many weights in sequence, one must pass update=False so
            # that the existing weights and notional_value are not recalculated
            # before finishing.
            if c.fixed_income:
                delta = weight * base - c.weight * self.notional_value
                c.transact(delta, update=update)
            else:
                delta = weight * base - c.weight * self.notional_value
                c.allocate(delta, update=update)
        else:
            delta = weight - c.weight
            c.allocate(delta * base, update=update)

    @cy.locals(update=cy.bint)
    def close(self, child, update=True):
        """
        Close a child position - alias for rebalance(0, child). This will also
        flatten (close out all) the child's children.

        Args:
            * child (str): Child, specified by name.
        """
        c = self.children[child]
        # flatten if children not None
        if c.children is not None and len(c.children) != 0:
            c.flatten()

        if self.fixed_income:
            if c.position != 0.0:
                c.transact(-c.position, update=update)
        else:
            if c.value != 0.0 and not np.isnan(c.value):
                c.allocate(-c.value, update=update)

    def flatten(self):
        """
        Close all child positions.
        """
        # go right to base alloc
        if self.fixed_income:
            [c.transact(-c.position, update=False) for c in self._childrenv if c.position != 0]
        else:
            [c.allocate(-c.value, update=False) for c in self._childrenv if c.value != 0]

        self.root.stale = True

    def run(self):
        """
        This is the main logic method. Override this method to provide some
        algorithm to execute on each date change. This method is called by
        backtester.
        """

    def set_commissions(self, fn):
        """
        Set commission (transaction fee) function.

        Args:
            fn (fn(quantity, price)): Function used to determine commission
            amount.

        """
        self.commission_fn = fn

        for c in self._childrenv:
            if isinstance(c, StrategyBase):
                c.set_commissions(fn)

    def get_transactions(self):
        """
        Helper function that returns the transactions in the following format:

            Date, Security | quantity, price

        The result is a MultiIndex DataFrame.
        """
        # get prices for each security in the strategy & create unstacked
        # series
        prc = pd.DataFrame({x.name: x.prices for x in self.securities}).unstack()

        # get security positions
        positions = pd.DataFrame()
        for x in self.securities:
            if x.name in positions.columns:
                positions[x.name] += x.positions
            else:
                positions[x.name] = x.positions
        # trades are diff
        trades = positions.diff()
        # must adjust first row
        trades.iloc[0] = positions.iloc[0]
        # now convert to unstacked series, dropping nans along the way
        trades = trades[trades != 0].unstack().dropna()

        # Adjust prices for bid/offer paid if needed
        if self._bidoffer_set:
            bidoffer = pd.DataFrame({x.name: x.bidoffers_paid for x in self.securities}).unstack()
            prc += bidoffer / trades

        res = pd.DataFrame({"price": prc, "quantity": trades}).dropna(subset=["quantity"])

        # set names
        res.index.names = ["Security", "Date"]

        # swap levels so that we have (date, security) as index and sort
        res = res.swaplevel().sort_index()

        return res

    @cy.locals(q=cy.double, p=cy.double)
    def _dflt_comm_fn(self, q, p):
        return 0.0

    def _create_child_if_needed(self, child):
        if child not in self.children:
            # Look up name in lazy children, or create a default security
            c = self._lazy_children.pop(child, Security(child))
            c.lazy_add = False

            # add child to tree
            self._add_children([c], dc=False)
            c.setup(self._universe, **self._setup_kwargs)

            # update to bring up to speed
            c.update(self.now)


class Strategy(StrategyBase):
    """
    Strategy expands on the StrategyBase and incorporates Algos.

    Basically, a Strategy is built by passing in a set of algos. These algos
    will be placed in an Algo stack and the run function will call the stack.

    Furthermore, two class attributes are created to pass data between algos.
    perm for permanent data, temp for temporary data.

    Args:
        * name (str): Strategy name
        * algos (list): List of Algos to be passed into an AlgoStack
        * children (dict, list): Children - useful when you want to create
          strategies of strategies
          Children can be any type of Node or str.
          String values correspond to children which will be lazily created
          with that name when needed.
        * parent (Node): The parent Node

    Attributes:
        * stack (AlgoStack): The stack
        * temp (dict): A dict containing temporary data - cleared on each call
          to run. This can be used to pass info to other algos.
        * perm (dict): Permanent data used to pass info from one algo to
          another. Not cleared on each pass.

    """

    def __init__(self, name, algos=None, children=None, parent=None):
        super().__init__(name, children=children, parent=parent)
        if algos is None:
            algos = []
        from .algo import AlgoStack

        self.stack = AlgoStack(*algos)
        self.temp = {}
        self.perm = {}

    def run(self):
        # clear out temp data
        self.temp = {}

        # run algo stack
        self.stack(self)

        # run children
        for c in self._childrenv:
            c.run()


class FixedIncomeStrategy(Strategy):
    """
    FixedIncomeStrategy is an alias for Strategy where the fixed_income flag
    is set to True.

    For this type of strategy:
        - capital allocations are not necessary, and initial capital is not used
        - bankruptcy is disabled (and should be modeled explicitly via an Algo)
        - weights are based off notional_value rather than value
        - strategy price is computed from additive PNL returns
          per unit of current notional_value, with a reference price of PAR.
          :class:`RenormalizedFixedIncomeResult<bt.backtest.RenormalizedFixedIncomeResult>`
          can be used to re-calculate the price-based performance statistics
          using different normalization schemes on total pnl.
        - "transact" assumes the role of "allocate", in order to buy/sell
          children on a weighted notional basis
        - "rebalance" adjusts notionals rather than capital allocations based
          on weights
    """

    def __init__(self, name, algos=None, children=None):
        super().__init__(name, algos=algos, children=children)
        self._fixed_income = True
