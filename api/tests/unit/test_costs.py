import unittest

from app.services.llm.costs import compute_cost_usd


class TestComputeCost(unittest.TestCase):
    def test_prices_input_cached_and_output_tokens_per_million(self):
        # gpt-4o-mini: $0.15 in, $0.075 cached, $0.6 out per 1M tokens
        cost = compute_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000, 1_000_000)

        self.assertAlmostEqual(cost, 0.15 + 0.075 + 0.6)

    def test_zero_tokens_cost_nothing(self):
        self.assertEqual(compute_cost_usd("gpt-4o", 0, 0, 0), 0.0)

    def test_unknown_model_raises(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            compute_cost_usd("not-a-model", 1, 1, 1)


if __name__ == "__main__":
    unittest.main()
