# Thin shim — all logic has moved to localsignal_engine/signal/
from localsignal_engine.signal.enrichment import enrich_report_signals_with_llm

__all__ = ["enrich_report_signals_with_llm"]
