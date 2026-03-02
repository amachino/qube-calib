"""Numeric helpers used by pulse timing quantization."""

from __future__ import annotations

import math


def ceil(value: float, unit: float = 1) -> float:
    """
    Round a value up to the nearest multiple of `unit`.

    Parameters
    ----------
    value : float
        Value to round.
    unit : float, default=1
        Quantization step.

    Returns
    -------
    float
        Rounded value.
    """
    exponent = math.floor(math.log10(unit))
    mantissa = unit * 10 ** (-exponent)
    retval = None
    if exponent < 0:
        retval = (
            math.ceil(value * 10 ** (-exponent) / mantissa) * mantissa * 10**exponent
        )
    else:
        retval = (
            math.ceil(value / 10 ** (exponent) / mantissa) * mantissa * 10**exponent
        )
    if (retval - unit) - value < 1e-16:
        return retval - unit
    else:
        return retval


def floor(value: float, unit: float = 1) -> float:
    """
    Round a value down to the nearest multiple of `unit`.

    Parameters
    ----------
    value : float
        Value to round.
    unit : float, default=1
        Quantization step.

    Returns
    -------
    float
        Rounded value.
    """
    exponent = math.floor(math.log10(unit))
    mantissa = unit * 10 ** (-exponent)
    retval = None
    if exponent < 0:
        retval = (
            math.floor(value * 10 ** (-exponent) / mantissa) * mantissa * 10**exponent
        )
    else:
        retval = (
            math.floor(value / 10 ** (exponent) / mantissa) * mantissa * 10**exponent
        )
    if (retval + unit) - value < 1e-16:
        return retval + unit
    else:
        return retval
