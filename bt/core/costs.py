"""
Cost models for transaction cost estimation.
"""

from __future__ import annotations

import cython as cy


class CostModel:
    """
    Nonlinear transaction cost model.

    Given a trade quantity ``q``, execution price ``p``, bar volume ``V``
    and bar volatility ``sigma``, returns the total trade cost in currency
    units. Intended as an alternative to the flat ``commissions=fn(q, p)``
    hook for models that depend on market depth and volatility (square-root
    law, Almgren-Chriss, etc.). Commissions / spread / fees are absorbed
    into the model's linear term where applicable.

    Subclasses implement ``cost(q, p, V, sigma) -> float``.
    """

    @cy.locals(q=cy.double, p=cy.double, V=cy.double, sigma=cy.double)
    def cost(self, q, p, V, sigma):
        raise NotImplementedError


class SqrtCostModel(CostModel):
    """
    Square-root law of market impact (Toth et al. 2011).

    Instantaneous impact as a fraction of price is
    ``I(x) = Y * sigma * sqrt(|x| / V)``. Integrating the impact profile
    over a block trade yields the 2/3 prefactor on the cost:

        cost = (2/3) * Y * sigma * |q| * sqrt(|q| / V) * p

    Args:
        * Y (float): empirical coefficient, typically 0.5-1.0.
          Default 0.6.

    References:
        Toth, B. et al. (2011). Anomalous Price Impact and the Critical
        Nature of Liquidity in Financial Markets. Physical Review X 1(2).
    """

    def __init__(self, Y=0.6):
        self.Y = Y

    @cy.locals(q=cy.double, p=cy.double, V=cy.double, sigma=cy.double, abs_q=cy.double)
    def cost(self, q, p, V, sigma):
        abs_q = abs(q)
        if V <= 0.0 or abs_q == 0.0:
            return 0.0
        return (2.0 / 3.0) * self.Y * sigma * abs_q * (abs_q / V) ** 0.5 * p


class AlmgrenChrissCostModel(CostModel):
    """
    Almgren-Chriss three-component transaction cost (Almgren & Chriss 2001).

        cost =   0.5 * alpha * sigma * (|q|/V) * |q| * p   (permanent, triangular)
               + epsilon * |q| * p                         (linear temp: spread/fees)
               + beta * sigma * (|q|/V) * |q| * p          (quadratic temp: depth)

    The permanent-impact term is the triangular cost paid as the block
    executes: the average execution price drifts from ``P`` to ``P + dP``,
    so the block pays ``0.5 * dP * |q|``. The persistent price shift itself
    is not tracked by this cost-only model.

    Args:
        * alpha (float): permanent impact coefficient. Default 1.0.
        * beta (float): quadratic temporary (depth) coefficient. Default 1.0.
        * epsilon (float): linear temporary (half-spread) fraction of price.
          Default 0.0005 (5 bps).

    References:
        Almgren, R., & Chriss, N. (2001). Optimal execution of portfolio
        transactions. Journal of Risk 3(2), 5-39.
    """

    def __init__(self, alpha=1.0, beta=1.0, epsilon=0.0005):
        self.alpha = alpha
        self.beta = beta
        self.epsilon = epsilon

    @cy.locals(q=cy.double, p=cy.double, V=cy.double, sigma=cy.double, abs_q=cy.double, part=cy.double)
    def cost(self, q, p, V, sigma):
        abs_q = abs(q)
        if V <= 0.0 or abs_q == 0.0:
            return 0.0
        part = abs_q / V
        return ((0.5 * self.alpha + self.beta) * sigma * part + self.epsilon) * abs_q * p
