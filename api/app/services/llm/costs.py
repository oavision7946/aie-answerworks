from app.core.settings import Pricing
from app.services.llm.base import Usage


def compute_cost_usd(pricing: Pricing | None, usage: Usage) -> float | None:
    """Cost in USD, or None when the model has no pricing configured."""
    if pricing is None:
        return None
    uncached_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    return (
        (uncached_input / 1_000_000) * pricing.input
        + (usage.cached_input_tokens / 1_000_000) * pricing.cached_input_price
        + (usage.output_tokens / 1_000_000) * pricing.output
    )
