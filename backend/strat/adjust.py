"""Point-in-time split adjustment.

Bars are stored raw. A split applies to earlier bars only when its ex-date is on or before the
date being viewed, so a later split cannot rewrite a historical scan or a ``STRAT_AS_OF`` cut-off.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd

Split = tuple[str, float]  # ex-date (YYYY-MM-DD), ratio (4.0 means 4-for-1)


def apply_splits(df: pd.DataFrame, splits: Sequence[Split], as_of, *, volume: bool = True) -> pd.DataFrame:
    """Divide OHLC and multiply volume by splits whose ex-date is after the bar and on or before ``as_of``.

    ``volume=False`` adjusts prices only: spin-off factors change the price level, not the share count.
    """
    if df is None or df.empty or not splits:
        return df
    as_of_ts = pd.Timestamp(as_of)
    if as_of_ts.tzinfo is not None:
        as_of_ts = as_of_ts.tz_localize(None)
    factor = pd.Series(1.0, index=df.index)
    for ex_date, ratio in splits:
        ratio = float(ratio)
        if not ratio or ratio == 1.0:
            continue
        ex = pd.Timestamp(ex_date)
        if ex <= as_of_ts:
            factor.loc[df.index < ex] *= ratio
    if bool((factor == 1.0).all()):
        return df
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = out[col] / factor
    if volume and "volume" in out.columns:
        out["volume"] = out["volume"] * factor
    return out
