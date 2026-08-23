"""
Security node classes.
"""

from __future__ import annotations

import math

import cython as cy
import numpy as np
import pandas as pd

from .node import TOL, Node, is_zero


class SecurityBase(Node):
    """
    Security Node. Used to define a security within a tree.
    A Security's has no children. It simply models an asset that can be bought
    or sold.

    Args:
        * name (str): Security name
        * multiplier (float): security multiplier - typically used for
          derivatives or to trade in lots. The quantity of the Security will
          always be multiplied by this to determine the underlying amount.
        * lazy_add (bool): Flag to control whether instrument should be added
          to strategy children lazily, i.e. only when there is a transaction
          on the instrument. This improves performance of strategies which
          transact on a sparse set of children.

    Attributes:
        * name (str): Security name
        * parent (Security): Security parent
        * root (Security): Root node of the tree (topmost node)
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Security is stale and need
          updating
        * prices (TimeSeries): Security prices.
        * price (float): last price
        * outlays (TimeSeries): Series of outlays. Positive outlays mean
          capital was allocated to security and security consumed that
          amount.  Negative outlays are the opposite. This can be useful for
          calculating turnover at the strategy level.
        * value (float): last value - basically position * price * multiplier
        * weight (float): weight in parent
        * full_name (str): Name including parents' names
        * members (list): Current Security + strategy's children
        * position (float): Current position (quantity).
        * bidoffer (float): Current bid/offer spread
        * bidoffers (TimeSeries): Series of bid/offer spreads
        * bidoffer_paid (TimeSeries): Series of bid/offer paid on transactions
    """

    _last_pos = cy.declare(cy.double)
    _position = cy.declare(cy.double)
    multiplier = cy.declare(cy.double)
    _prices_set = cy.declare(cy.bint)
    _needupdate = cy.declare(cy.bint)
    _outlay = cy.declare(cy.double)
    _bidoffer = cy.declare(cy.double)

    @cy.locals(multiplier=cy.double)
    def __init__(self, name, multiplier=1, lazy_add=False):
        Node.__init__(self, name, parent=None, children=None)
        self._value = 0
        self._price = 0
        self._weight = 0
        self._position = 0
        self.multiplier = multiplier
        self.lazy_add = lazy_add

        # opt
        self._last_pos = 0
        self._issec = True
        self._needupdate = True
        self._outlay = 0
        self._bidoffer = 0

    @property
    def price(self):
        """
        Current price.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        return self._price

    @property
    def prices(self):
        """
        TimeSeries of prices.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        return self._prices.loc[: self.now]

    @property
    def values(self):
        """
        TimeSeries of values.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._values.loc[: self.now]

    @property
    def notional_values(self):
        """
        TimeSeries of notional values.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._notl_values.loc[: self.now]

    @property
    def position(self):
        """
        Current position
        """
        # no stale check needed
        return self._position

    @property
    def positions(self):
        """
        TimeSeries of positions.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._positions.loc[: self.now]

    @property
    def outlays(self):
        """
        TimeSeries of outlays. Positive outlays (buys) mean this security
        received and consumed capital (capital was allocated to it). Negative
        outlays are the opposite (the security close/sold, and returned capital
        to parent).
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._outlays.loc[: self.now]

    @property
    def bidoffer(self):
        """
        Current bid/offer spread.
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        return self._bidoffer

    @property
    def bidoffers(self):
        """
        TimeSeries of bid/offer spread
        """
        if self._bidoffer_set:
            # if accessing and stale - update first
            if self._needupdate or self.now != self.parent.now:
                self.update(self.root.now)
            return self._bidoffers.loc[: self.now]
        else:
            raise RuntimeError('Bid/offer accounting not turned on: "bidoffer" argument not provided during setup')

    @property
    def bidoffer_paid(self):
        """
        TimeSeries of bid/offer spread paid on transactions in the current step
        """
        # if accessing and stale - update first
        if self._needupdate or self.now != self.parent.now:
            self.update(self.root.now)
        return self._bidoffer_paid

    @property
    def bidoffers_paid(self):
        """
        TimeSeries of bid/offer spread paid on transactions in the current step
        """
        if self._bidoffer_set:
            # if accessing and stale - update first
            if self._needupdate or self.now != self.parent.now:
                self.update(self.root.now)
            if self.root.stale:
                self.root.update(self.root.now, None)
            return self._bidoffers_paid.loc[: self.now]
        else:
            raise RuntimeError('Bid/offer accounting not turned on: "bidoffer" argument not provided during setup')

    def setup(self, universe, **kwargs):
        """
        Setup Security with universe. Speeds up future runs.

        Args:
            * universe (DataFrame): DataFrame of prices with security's name as
              one of the columns.
            * bidoffer (DataFrame): Optional argument that represents the
              bid/offer spread on each security across time. If provided, the
              strategy will account for these costs when rebalancing.
            * kwargs (dict): Dictionary of additional information needed by
              the strategy. In particular, often takes the form of a DataFrame
              of security level information (i.e. signals, risk, etc).
        """
        # if we already have all the prices, we will store them to speed up
        # future updates
        try:
            prices = universe[self.name]
        except KeyError:
            prices = None

        # setup internal data
        if prices is not None:
            self._prices = prices
            self.data = pd.DataFrame(
                index=universe.index,
                columns=["value", "position", "notional_value"],
                data=0.0,
            )
            self._prices_set = True
        else:
            self.data = pd.DataFrame(
                index=universe.index,
                columns=["price", "value", "position", "notional_value"],
            )
            self._prices = self.data["price"]
            self._prices_set = False

        self._values = self.data["value"]
        self._notl_values = self.data["notional_value"]
        self._positions = self.data["position"]

        # add _outlay
        self.data["outlay"] = 0.0
        self._outlays = self.data["outlay"]

        # save bidoffer, if provided
        if "bidoffer" in kwargs:
            self._bidoffer_set = True
            self._bidoffers = kwargs["bidoffer"]
            try:
                bidoffers = self._bidoffers[self.name]
            except KeyError:
                bidoffers = None

            if bidoffers is not None:
                if bidoffers.index.equals(universe.index):
                    self._bidoffers = bidoffers
                else:
                    raise ValueError("Index of bidoffer must match universe data")
            else:
                self.data["bidoffer"] = 0.0
                self._bidoffers = self.data["bidoffer"]

            self.data["bidoffer_paid"] = 0.0
            self._bidoffers_paid = self.data["bidoffer_paid"]

        self._data_ready = True

    def _sync_data(self):
        if not self._prices_set:
            self._data["price"] = self._prices
        self._data["value"] = self._values
        self._data["notional_value"] = self._notl_values
        self._data["position"] = self._positions
        self._data["outlay"] = self._outlays
        if self._bidoffer_set:
            self._data["bidoffer_paid"] = self._bidoffers_paid

    @cy.locals(prc=cy.double)
    def update(self, date, data=None, inow=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """
        # filter for internal calls when position has not changed - nothing to
        # do. Internal calls (stale root calls) have None data. Also want to
        # make sure date has not changed, because then we do indeed want to
        # update.
        if date == self.now and self._last_pos == self._position:
            return

        if inow is None:
            if date == 0:
                inow = 0
            else:
                inow = self._data.index.get_loc(date)

        # date change - update price
        if date != self.now:
            # update now
            self.now = date

            if self._prices_set:
                self._price = self._prices.iloc[inow]
            # traditional data update
            elif data is not None:
                prc = data[self.name]
                self._price = prc
                self._prices.iloc[inow] = prc

            # update bid/offer
            if self._bidoffer_set:
                self._bidoffer = self._bidoffers.iloc[inow]
                self._bidoffer_paid = 0.0

        self._positions.iloc[inow] = self._position
        self._last_pos = self._position

        if np.isnan(self._price):
            if is_zero(self._position):
                self._value = 0
            else:
                raise ValueError(f"Position is open (non-zero: {self._position}) and latest price is NaN for security {self.name} on {date}. Cannot update node value.")
        else:
            self._value = self._position * self._price * self.multiplier

        self._notl_value = self._value

        self._values.iloc[inow] = self._value
        self._notl_values.iloc[inow] = self._notl_value

        if is_zero(self._weight) and is_zero(self._position):
            self._needupdate = False

        # save outlay to outlays
        if self._outlay != 0:
            self._outlays.iloc[inow] += self._outlay
            # reset outlay back to 0
            self._outlay = 0

        if self._bidoffer_set:
            self._bidoffers_paid.iloc[inow] = self._bidoffer_paid

    @cy.locals(amount=cy.double, update=cy.bint, q=cy.double, outlay=cy.double, i=cy.int)
    def allocate(self, amount, update=True):
        """
        This allocates capital to the Security. This is the method used to
        buy/sell the security.

        A given amount of shares will be determined on the current price, a
        commission will be calculated based on the parent's commission fn, and
        any remaining capital will be passed back up  to parent as an
        adjustment.

        Args:
            * amount (float): Amount of adjustment.
            * update (bool): Force update?

        """

        # will need to update if this has been idle for a while...
        # update if needupdate or if now is stale
        # fetch parent's now since our now is stale
        if self._needupdate or self.now != self.parent.now:
            self.update(self.parent.now)

        # ignore 0 alloc
        # Note that if the price of security has dropped to zero, then it
        # should never be selected by SelectAll, SelectN etc. I.e. we should
        # not open the position at zero price. At the same time, we are able
        # to close it at zero price, because at that point amount=0.
        # Note also that we don't erase the position in an asset which price
        # has dropped to zero (though the weight will indeed be = 0)
        if is_zero(amount):
            return

        if self.parent is self or self.parent is None:
            raise RuntimeError("Cannot allocate capital to a parentless security")

        if is_zero(self._price) or np.isnan(self._price):
            raise ValueError(f"Cannot allocate capital to {self.name} because price is {self._price} as of {self.parent.now}")

        # buy/sell
        # determine quantity - must also factor in commission
        # closing out?
        if is_zero(amount + self._value):
            q = -self._position
        else:
            q = amount / (self._price * self.multiplier)
            if self.integer_positions:
                if (self._position > 0) or (is_zero(self._position) and (amount > 0)):
                    # if we're going long or changing long position
                    q = math.floor(q)
                else:
                    # if we're going short or changing short position
                    q = math.ceil(q)

        # if q is 0 nothing to do
        if is_zero(q) or np.isnan(q):
            return

        # unless we are closing out a position (q == -position)
        # we want to ensure that
        #
        # - In the event of a positive amount, this indicates the maximum
        # amount a given security can use up for a purchase. Therefore, if
        # commissions push us above this amount, we cannot buy `q`, and must
        # decrease its value
        #
        # - In the event of a negative amount, we want to 'raise' at least the
        # amount indicated, no less. Therefore, if we have commission, we must
        # sell additional units to fund this requirement. As such, q must once
        # again decrease.
        #
        if q != -self._position:
            full_outlay, _, _, _ = self.outlay(q)

            # if full outlay > amount, we must decrease the magnitude of `q`
            # this can potentially lead to an infinite loop if the commission
            # per share > price per share. However, we cannot really detect
            # that in advance since the function can be non-linear (say a fn
            # like max(1, abs(q) * 0.01). Nevertheless, we want to avoid these
            # situations.
            # cap the maximum number of iterations to 1e4 and raise exception
            # if we get there
            # if integer positions then we know we are stuck if q doesn't change

            # if integer positions is false then we want full_outlay == amount
            # if integer positions is true then we want to be at the q where
            #   if we bought 1 more then we wouldn't have enough cash
            i = 0
            last_q = q
            last_amount_short = full_outlay - amount
            while not np.isclose(full_outlay, amount, rtol=TOL) and q != 0:
                dq_wout_considering_tx_costs = (full_outlay - amount) / (self._price * self.multiplier)
                q = q - dq_wout_considering_tx_costs

                if self.integer_positions:
                    q = math.floor(q)

                full_outlay, _, _, _ = self.outlay(q)

                # if our q is too low and we have integer positions
                # then we know that the correct quantity is the one  where
                # the outlay of q + 1 < amount. i.e. if we bought one more
                # position then we wouldn't have enough cash
                if self.integer_positions:
                    full_outlay_of_1_more, _, _, _ = self.outlay(q + 1)

                    if full_outlay < amount and full_outlay_of_1_more > amount:
                        break

                # if not integer positions then we should keep going until
                # full_outlay == amount or is close enough

                i = i + 1
                if i > 1e4:
                    raise RuntimeError(
                        "Potentially infinite loop detected. This occurred "
                        "while trying to reduce the amount of shares purchased"
                        " to respect the outlay <= amount rule. This is most "
                        "likely due to a commission function that outputs a "
                        "commission that is greater than the amount of cash "
                        "a short sale can raise."
                    )

                if self.integer_positions and last_q == q:
                    raise RuntimeError(
                        "Newton Method like root search for quantity is stuck!"
                        " q did not change in iterations so it is probably a bug"
                        " but we are not entirely sure it is wrong! Consider "
                        " changing to warning."
                    )
                last_q = q

                if np.abs(full_outlay - amount) > np.abs(last_amount_short):
                    raise RuntimeError(
                        "The difference between what we have raised with q and"
                        " the amount we are trying to raise has gotten bigger since"
                        " last iteration! full_outlay should always be approaching"
                        " amount! There may be a case where the commission fn is"
                        " not smooth"
                    )
                last_amount_short = full_outlay - amount

        self.transact(q, update, False)

    @cy.locals(
        q=cy.double,
        update=cy.bint,
        update_self=cy.bint,
        outlay=cy.double,
        bidoffer=cy.double,
    )
    def transact(self, q, update=True, update_self=True, price=None):
        """
        This transacts the Security. This is the method used to
        buy/sell the security for a given quantity.

        The amount of shares is explicitly provided, a
        commission will be calculated based on the parent's commission fn, and
        any remaining capital will be passed back up  to parent as an
        adjustment.

        Args:
            * amount (float): Amount of adjustment.
            * update (bool): Force update on parent due to transaction proceeds
            * update_self (bool): Check for update on self
            * price (float): Optional price if the transaction happens at a bespoke level
        """
        # will need to update if this has been idle for a while...
        # update if needupdate or if now is stale
        # fetch parent's now since our now is stale
        if update_self and (self._needupdate or self.now != self.parent.now):
            self.update(self.parent.now)

        # if q is 0 nothing to do
        if is_zero(q) or np.isnan(q):
            return

        if price is not None and not self._bidoffer_set:
            raise ValueError('Cannot transact at custom prices when "bidoffer" has not been passed during setup to enable bid-offer tracking.')

        # this security will need an update, even if pos is 0 (for example if
        # we close the positions, value and pos is 0, but still need to do that
        # last update)
        self._needupdate = True

        # adjust position & value
        self._position += q

        # calculate proper adjustment for parent
        # parent passed down amount so we want to pass
        # -outlay back up to parent to adjust for capital
        # used
        full_outlay, outlay, fee, bidoffer = self.outlay(q, p=price)

        # store outlay for future reference
        self._outlay += outlay
        self._bidoffer_paid += bidoffer

        # call parent
        self.parent.adjust(-full_outlay, update=update, flow=False, fee=fee)

    @cy.locals(q=cy.double, p=cy.double)
    def commission(self, q, p):
        """
        Calculates the commission (transaction fee) based on quantity and
        price.  Uses the parent's commission_fn.

        Args:
            * q (float): quantity
            * p (float): price

        """
        return self.parent.commission_fn(q, p)

    @cy.locals(q=cy.double)
    def outlay(self, q, p=None):
        """
        Determines the complete cash outlay (including commission) necessary
        given a quantity q.
        Second returning parameter is a commission itself.

        Args:
            * q (float): quantity
            * p (float): price override
        """
        if p is None:
            fee = self.commission(q, self._price * self.multiplier)
            bidoffer = abs(q) * 0.5 * self._bidoffer * self.multiplier
        else:
            # price override provided: custom transaction
            fee = self.commission(q, p * self.multiplier)
            bidoffer = q * (p - self._price) * self.multiplier

        outlay = q * self._price * self.multiplier + bidoffer

        return outlay + fee, outlay, fee, bidoffer

    def run(self):
        """
        Does nothing - securities have nothing to do on run.
        """


class Security(SecurityBase):
    """
    A standard security with no special features, and where notional value
    is measured based on market value (notional times price).
    It exists to be able to identify standard securities from nonstandard
    ones via isinstance, i.e. isinstance( sec, Security ) would only return
    True for a vanilla security, whereas SecurityBase would return True for
    all securities.
    """


class FixedIncomeSecurity(SecurityBase):
    """
    A Fixed Income Security is a security where notional value is
    measured only based on the quantity (par value) of the security.
    Only relevant when using :class:`FixedIncomeStrategy <bt.core.FixedIncomeStrategy>`.
    """

    @cy.locals(coupon=cy.double)
    def update(self, date, data=None, inow=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """

        if inow is None:
            if date == 0:
                inow = 0
            else:
                inow = self._data.index.get_loc(date)

        super().update(date, data, inow)

        # For fixed income securities (bonds, swaps), notional value is position size, not value!
        self._notl_value = self._position
        self._notl_values.iloc[inow] = self._notl_value


class CouponPayingSecurity(FixedIncomeSecurity):
    """
    CouponPayingSecurity expands on SecurityBase to handle securities which
    pay (possibly irregular) coupons (or other forms of cash disbursement).
    More generally, this can include instruments with any sort of carry,
    including (potentially asymmetric) holding costs.

    Args:
        * name (str): Security name
        * multiplier (float): security multiplier - typically used for
          derivatives.
        * fixed_income (bool): Flag to control whether notional_value is set.
        * lazy_add (bool): Flag to control whether instrument should be added
          to strategy children lazily, i.e. only when there is a transaction
          on the instrument. This improves performance of strategies which
          transact on a sparse set of children.

    Attributes:
        * SecurityBase attributes
        * coupon (float): Current coupon payment (quantity).
        * holding_cost (float): Current holding cost (quantity).


    Represents a coupon-paying security, where coupon payments adjust
    the capital of the parent. Coupons and costs must be passed in during setup.
    """

    _coupon = cy.declare(cy.double)
    _holding_cost = cy.declare(cy.double)

    @cy.locals(multiplier=cy.double)
    def __init__(self, name, multiplier=1, fixed_income=True, lazy_add=False):
        super().__init__(name, multiplier)
        self._coupon = 0
        self._holding_cost = 0
        self._fixed_income = fixed_income
        self.lazy_add = lazy_add

    def setup(self, universe, **kwargs):
        """
        Setup Security with universe and coupon data. Speeds up future runs.

        Args:
            * universe (DataFrame): DataFrame of prices with security's name as
              one of the columns.
            * coupons (DataFrame): Manatory DataFrame of coupon/carry amount with
              the same schema as universe.
            * cost_long (DataFrame): Optional DataFrame containing the cost of
              holding a unit long position in the security (i.e. funding).
            * cost_short (DataFrame): Optional DataFrame containing the cost of
              holding a unit short position in the security (i.e. repo).
            * kwargs (dict): Dictionary of additional information needed by
              the strategy. In particular, often takes the form of a DataFrame
              of security level information (i.e. signals, risk, etc).
        """
        super().setup(universe, **kwargs)

        # Handle coupons
        if "coupons" not in kwargs:
            raise ValueError('"coupons" must be passed to setup for a CouponPayingSecurity')

        try:
            self._coupons = kwargs["coupons"][self.name]
        except KeyError:
            self._coupons = None

        if self._coupons is None or not self._coupons.index.equals(universe.index):
            raise ValueError("Index of coupons must match universe data")

        # Handle holding costs
        try:
            self._cost_long = kwargs["cost_long"][self.name]
        except KeyError:
            self._cost_long = None
        try:
            self._cost_short = kwargs["cost_short"][self.name]
        except KeyError:
            self._cost_short = None

        self.data["coupon"] = 0.0
        self.data["holding_cost"] = 0.0
        self._coupon_income = self.data["coupon"]
        self._holding_costs = self.data["holding_cost"]

    def _sync_data(self):
        super()._sync_data()
        if hasattr(self, "_holding_costs"):
            self._data["coupon"] = self._coupon_income
            self._data["holding_cost"] = self._holding_costs

    @cy.locals(coupon=cy.double, cost=cy.double)
    def update(self, date, data=None, inow=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """
        if inow is None:
            if date == 0:
                inow = 0
            else:
                inow = self._data.index.get_loc(date)

        if self._coupons is None:
            raise RuntimeError(f"coupons have not been set for security {self.name}")

        # Standard update
        super().update(date, data, inow)

        coupon = self._coupons.iloc[inow]
        # If we were to call self.parent.adjust, then all the child weights would
        # need to be updated. If each security pays a coupon, then this happens for
        # each child. Instead, we store the coupon on self._capital, and it gets
        # swept up as part of the strategy update

        if np.isnan(coupon):
            if is_zero(self._position):
                self._coupon = 0.0
            else:
                raise ValueError(f"Position is open (non-zero) and latest coupon is NaN for security {self.name} on {date}. Cannot update node value.")
        else:
            self._coupon = self._position * coupon

        if self._position > 0 and self._cost_long is not None:
            cost = self._cost_long.iloc[inow]
            self._holding_cost = self._position * cost
        elif self._position < 0 and self._cost_short is not None:
            cost = self._cost_short.iloc[inow]
            self._holding_cost = -self._position * cost
        else:
            self._holding_cost = 0.0

        self._capital = self._coupon - self._holding_cost
        self._coupon_income.iloc[inow] = self._coupon
        self._holding_costs.iloc[inow] = self._holding_cost

    @property
    def coupon(self):
        """
        Current coupon payment (scaled by position)
        """
        if self.root.stale:  # Stale check needed because coupon paid depends on position
            self.root.update(self.root.now, None)
        return self._coupon

    @property
    def coupons(self):
        """
        TimeSeries of coupons paid (scaled by position)
        """
        if self.root.stale:  # Stale check needed because coupon paid depends on position
            self.root.update(self.root.now, None)
        return self._coupon_income.loc[: self.now]

    @property
    def holding_cost(self):
        """
        Current holding cost (scaled by position)
        """
        if self.root.stale:  # Stale check needed because coupon paid depends on position
            self.root.update(self.root.now, None)
        return self._holding_cost

    @property
    def holding_costs(self):
        """
        TimeSeries of coupons paid (scaled by position)
        """
        if self.root.stale:  # Stale check needed because coupon paid depends on position
            self.root.update(self.root.now, None)
        return self._holding_costs.loc[: self.now]


class HedgeSecurity(SecurityBase):
    """
    HedgeSecurity is a SecurityBase where the notional value is set to zero, and thus
    does not count towards the notional value of the strategy. It is intended for use
    in fixed income strategies.

    For example in a corporate bond strategy, the notional value might refer to the size
    of the corporate bond portfolio, and exclude the notional of treasury bonds or interest
    rate swaps used as hedges.
    """

    def update(self, date, data=None, inow=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """
        super().update(date, data, inow)
        self._notl_value = 0.0
        self._notl_values.iloc[:] = 0.0


class CouponPayingHedgeSecurity(CouponPayingSecurity):
    """
    CouponPayingHedgeSecurity is a CouponPayingSecurity where the notional value is set to zero, and thus
    does not count towards the notional value of the strategy. It is intended for use
    in fixed income strategies.

    For example in a corporate bond strategy, the notional value might refer to the size
    of the corporate bond portfolio, and exclude the notional of treasury bonds or interest
    rate swaps used as hedges.
    """

    def update(self, date, data=None, inow=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """
        super().update(date, data, inow)
        self._notl_value = 0.0
        self._notl_values.iloc[:] = 0.0
