from app.core.config import config_dir, load_model_costs


def compute_cost_usd(
    model: str, input_tokens: int, cached_input_tokens: int, output_tokens: int
) -> float:
    pricing = load_model_costs().get(model)
    if pricing is None:
        path = config_dir() / "model_costs.yaml"
        raise ValueError(f"Model {model!r} is not configured in {path}")

    return (
        (input_tokens / 1_000_000) * pricing["input_tokens"]
        + (cached_input_tokens / 1_000_000) * pricing["cached_input"]
        + (output_tokens / 1_000_000) * pricing["output_tokens"]
    )
