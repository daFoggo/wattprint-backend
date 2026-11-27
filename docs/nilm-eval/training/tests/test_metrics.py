import math
import unittest

import torch

from training.metrics import NILMMetricAccumulator, compute_nilm_metrics, energy_metrics, power_metrics, state_metrics


class MetricsTests(unittest.TestCase):
    def test_epoch_accumulator_matches_global_metrics_instead_of_batch_average(self):
        predicted = torch.tensor([[[0.0, 20.0, 10.0], [0.0, 0.0, 0.0]], [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]])
        target = torch.tensor([[[0.0, 10.0, 20.0], [0.0, 0.0, 0.0]], [[10.0, 0.0, 0.0], [0.0, 0.0, 0.0]]])
        on = target >= 5
        valid = torch.ones_like(on)
        valid[:, 1] = False
        accumulator = NILMMetricAccumulator(["Kettle", "Microwave"], [5.0, 5.0])
        for i in range(2):
            accumulator.update(predicted[i : i + 1], target[i : i + 1], on[i : i + 1], valid[i : i + 1])
        result = accumulator.compute()
        reference = compute_nilm_metrics(predicted[:, 0], target[:, 0], predicted_on=predicted[:, 0] >= 5, target_on=on[:, 0], sample_duration_s=60)
        for name in ["mae_w", "rmse_w", "nde", "sae", "mr", "f1", "precision", "recall", "energy_error_kwh"]:
            self.assertAlmostEqual(result["per_device"]["Kettle"][name], reference[name])
            self.assertAlmostEqual(result["macro"][name], reference[name])
        self.assertAlmostEqual(result["macro"]["f1"], 0.8)
        self.assertTrue(math.isnan(result["per_device"]["Microwave"]["f1"]))

    def test_power_metrics_and_energy_cancellation(self):
        predicted = torch.tensor([0.0, 20.0, 10.0, 0.0])
        target = torch.tensor([0.0, 10.0, 20.0, 0.0])
        result = power_metrics(predicted, target)
        self.assertAlmostEqual(result["mae_w"], 5)
        self.assertAlmostEqual(result["mse_w2"], 50)
        self.assertAlmostEqual(result["rmse_w"], math.sqrt(50))
        self.assertAlmostEqual(result["nde"], 0.4)
        self.assertAlmostEqual(result["sae"], 0)
        self.assertAlmostEqual(result["nep"], 2 / 3)
        self.assertAlmostEqual(result["teca"], 2 / 3)
        self.assertAlmostEqual(result["mr"], 0.5)

    def test_energy_uses_actual_intervals(self):
        predicted = torch.tensor([0.0, 20.0, 10.0, 0.0])
        target = torch.tensor([0.0, 10.0, 20.0, 0.0])
        result = energy_metrics(predicted, target, torch.tensor([3600.0, 1800.0, 3600.0, 3600.0]))
        self.assertAlmostEqual(result["predicted_energy_kwh"], 0.02)
        self.assertAlmostEqual(result["target_energy_kwh"], 0.025)
        self.assertAlmostEqual(result["energy_error_kwh"], 0.005)
        self.assertAlmostEqual(result["relative_energy_error"], 0.2)
        self.assertAlmostEqual(result["energy_bias_kwh"], -0.005)

    def test_state_confusion_counts_and_missing_positive_class(self):
        result = state_metrics(torch.tensor([0, 1, 0, 1]), torch.tensor([0, 1, 1, 0]))
        for name in ("tp", "fp", "fn", "tn"):
            self.assertEqual(result[name], 1)
        for name in ("precision", "recall", "f1", "accuracy", "false_negative_rate"):
            self.assertAlmostEqual(result[name], 0.5)
        result = state_metrics(torch.zeros(3), torch.zeros(3))
        self.assertEqual(result["f1"], 0)
        self.assertEqual(result["accuracy"], 1)
        self.assertTrue(math.isnan(result["false_negative_rate"]))

    def test_missing_labels_zero_denominators_and_invalid_predictions(self):
        target = torch.tensor([0.0, float("nan"), 0.0])
        predicted = torch.tensor([2.0, float("nan"), 100.0])
        valid = torch.tensor([True, True, False])
        result = power_metrics(predicted, target, valid)
        self.assertEqual(result["valid_count"], 1)
        self.assertAlmostEqual(result["coverage"], 1 / 3)
        self.assertEqual(result["mae_w"], 2)
        self.assertTrue(math.isnan(result["nde"]))
        self.assertTrue(math.isnan(result["sae"]))
        result = power_metrics(predicted, target, torch.zeros_like(valid))
        self.assertTrue(math.isnan(result["mae_w"]))
        self.assertEqual(result["valid_count"], 0)
        with self.assertRaisesRegex(AssertionError, "phải hữu hạn"):
            power_metrics(torch.tensor([float("nan")]), torch.ones(1))
        with self.assertRaisesRegex(AssertionError, "thời lượng|Thời lượng"):
            energy_metrics(torch.ones(1), torch.ones(1), -1)

    def test_combined_metrics_with_device_slices(self):
        target = torch.tensor([[[0.0, 10.0], [10.0, 0.0]]])
        prediction = target.clone().requires_grad_()
        states = target >= 5
        result = compute_nilm_metrics(prediction[:, 0], target[:, 0], sample_duration_s=10, predicted_on=states[:, 0], target_on=states[:, 0])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["f1"], 1)
        self.assertEqual(result["energy_error_kwh"], 0)
        self.assertIsNone(prediction.grad)
        with self.assertRaisesRegex(AssertionError, "đồng thời"):
            compute_nilm_metrics(prediction, target, predicted_on=states)


if __name__ == "__main__":
    unittest.main()
