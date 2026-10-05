import unittest

from app.core.settings import Pricing
from app.services.llm.base import Usage
from app.services.llm.costs import compute_cost_usd


class TestComputeCost(unittest.TestCase):
    def test_prices_uncached_cached_and_output_tokens_per_million(self):
        pricing = Pricing(input=2.0, cached_input=0.5, output=8.0)
        # 1M prompt tokens of which 400k were cached: 600k * $2 + 400k * $0.5 + 1M * $8
        usage = Usage(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=1_000_000)

        self.assertAlmostEqual(compute_cost_usd(pricing, usage), 1.2 + 0.2 + 8.0)

    def test_cached_price_defaults_to_input_price(self):
        pricing = Pricing(input=2.0, output=0.0)

        self.assertAlmostEqual(compute_cost_usd(pricing, Usage(1_000_000, 500_000, 0)), 2.0)

    def test_zero_usage_costs_nothing(self):
        self.assertEqual(compute_cost_usd(Pricing(input=1, output=1), Usage()), 0.0)

    def test_no_pricing_means_unknown_cost(self):
        self.assertIsNone(compute_cost_usd(None, Usage(10, 0, 10)))

    def test_cached_tokens_never_make_input_negative(self):
        pricing = Pricing(input=1.0, cached_input=0.0, output=0.0)

        self.assertEqual(
            compute_cost_usd(pricing, Usage(input_tokens=10, cached_input_tokens=20)), 0.0
        )


if __name__ == "__main__":
    unittest.main()
