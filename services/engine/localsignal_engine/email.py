# This module is kept as a thin shim for backwards compatibility.
# All logic lives in the localsignal_engine/email/ subpackage.
from localsignal_engine.email import send_latest_digest

__all__ = ["send_latest_digest"]
