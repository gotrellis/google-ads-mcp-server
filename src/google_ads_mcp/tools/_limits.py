"""Shared safety ceilings for write tools (defense-in-depth backstops).

The parent (clio-idx) enforces the real, tighter ceilings; these only reject
clearly out-of-range values on any path (incl. a direct chat-agent call), so a
fat-fingered or injected value never reaches a live account.
"""

from __future__ import annotations

import os

# Upper bound for a per-click bid (cpc_bid_micros), in micros of the account
# currency. Default 10_000_000_000 (~$10,000 CPC) — far above any sane bid, so
# it only trips on a unit confusion (dollars passed as micros) or a gross typo.
# Override via GOOGLE_ADS_MAX_CPC_BID_MICROS.
_DEFAULT_MAX_CPC_BID_MICROS = 10_000_000_000


def max_cpc_bid_micros() -> int:
    """Upper bound for cpc_bid_micros: env ``GOOGLE_ADS_MAX_CPC_BID_MICROS`` else the default."""
    try:
        value = int(os.environ.get("GOOGLE_ADS_MAX_CPC_BID_MICROS", ""))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_CPC_BID_MICROS
    return value if value > 0 else _DEFAULT_MAX_CPC_BID_MICROS
