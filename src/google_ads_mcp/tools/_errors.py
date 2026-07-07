"""Format Google Ads API errors into concise, actionable messages.

Tool ``call`` functions let exceptions propagate (see ``server.py``): the MCP
SDK turns a raised exception into a ``CallToolResult`` with ``isError=True`` and
the exception's string as the text content, which is how the parent (clio-idx)
detects failures. A raw ``GoogleAdsException`` stringifies to a verbose,
multi-line proto dump, so this collapses it to the per-error messages plus the
request id — what a human (or the parent's error UI) actually needs.
"""

from __future__ import annotations

from google.ads.googleads.errors import GoogleAdsException


def google_ads_error_message(exc: GoogleAdsException) -> str:
    """Return a one-or-more-line summary of a ``GoogleAdsException``.

    Reads ``exc.failure.errors[].message`` (the actionable text, e.g.
    "Too low.", "Resource was not found.") and the request id. Falls back to
    ``str(exc)`` if the failure carries no per-error messages.
    """
    messages = [
        err.message
        for err in getattr(getattr(exc, "failure", None), "errors", []) or []
        if getattr(err, "message", None)
    ]
    detail = "; ".join(messages) if messages else str(exc)
    request_id = getattr(exc, "request_id", None)
    if request_id:
        return f"Google Ads API error (request_id={request_id}): {detail}"
    return f"Google Ads API error: {detail}"
