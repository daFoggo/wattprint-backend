import tempfile
import unittest
from pathlib import Path

import torch

from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer
from training.train_twostage_nilmformer import (
    TwoStageLossConfig,
    train_twostage_nilmformer,
    two_stage_loss,
)


def make_model():
    return TwoStageNILMFormer(
        GRUConfig(c_out=2, conv_channels=4, hidden=4, num_layers=2, dropout=0),
        NILMFormerConfig(c_out=2, d_model=16, n_head=4, n_encoder_layers=1, dp_rate=0),
    )


class TwoStageTests(unittest.TestCase):
    def test_false_negative_regression_updates_detector_toward_on(self):
        model = make_model().train()
        with torch.no_grad():
            model.Detector.DownstreamTaskHead.weight.zero_()
            model.Detector.DownstreamTaskHead.bias.fill_(-2)
        output = model(torch.randn(2, 9, 16))
        output.logits.retain_grad()
        self.assertTrue((output.mask == 0).all())
        self.assertTrue((output.prediction == 0).all())
        losses = two_stage_loss(
            output,
            torch.full_like(output.power, 3),
            torch.ones_like(output.power),
            config=TwoStageLossConfig(detector_weight=0, auxiliary_on_weight=0),
        )
        losses["loss"].backward()
        # Gradient này chỉ đến từ MSE công suất sau mask; BCE không đóng góp.
        self.assertTrue((output.logits.grad < 0).all())
        self.assertTrue((model.Detector.DownstreamTaskHead.bias.grad < 0).all())

    def test_auxiliary_loss_trains_regressor_when_detector_is_off(self):
        model = make_model().train()
        with torch.no_grad():
            model.Detector.DownstreamTaskHead.weight.zero_()
            model.Detector.DownstreamTaskHead.bias.fill_(-2)
            model.Regressor.ProjStats2.weight.zero_()
            model.Regressor.ProjStats2.bias.zero_()
        output = model(torch.randn(2, 9, 16))
        losses = two_stage_loss(output, torch.full_like(output.power, 3), torch.ones_like(output.power))
        losses["loss"].backward()
        self.assertLess(float(model.Regressor.ProjStats2.bias.grad[0]), 0)

    def test_eval_uses_hard_mask_and_exact_zero(self):
        model = make_model().eval()
        with torch.no_grad():
            model.Detector.DownstreamTaskHead.weight.zero_()
            model.Detector.DownstreamTaskHead.bias.copy_(torch.tensor([-2.0, 2.0]))
            output = model(torch.randn(2, 9, 16))
        self.assertTrue((output.prediction[:, 0] == 0).all())
        torch.testing.assert_close(output.prediction[:, 1], output.power[:, 1])
        self.assertTrue((output.mask[:, 1] == 1).all())

    def test_missing_labels_excluded_and_empty_batch_rejected(self):
        output = make_model()(torch.randn(2, 9, 16))
        target = torch.ones_like(output.power)
        on = torch.ones_like(target)
        valid = torch.ones_like(target, dtype=torch.bool)
        target[0, 0, 0] = float("nan")
        valid[0, 1, 0] = False
        losses = two_stage_loss(output, target, on, valid)
        self.assertEqual(int(losses["valid_count"]), target.numel() - 2)
        losses["loss"].backward()
        for p in output.power, output.prediction:
            self.assertTrue(torch.isfinite(p).all())
        with self.assertRaisesRegex(AssertionError, "không chứa nhãn hợp lệ"):
            two_stage_loss(output, target, on, torch.zeros_like(valid))

    def test_train_validation_checkpoint_and_parameter_updates(self):
        torch.manual_seed(7)
        model = make_model()
        before_detector = model.Detector.DownstreamTaskHead.weight.detach().clone()
        before_regressor = model.Regressor.ProjStats2.weight.detach().clone()
        batches = [{"x": torch.randn(2, 9, 16), "power": torch.ones(2, 2, 16), "on": torch.ones(2, 2, 16)}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "best.pt"
            history = train_twostage_nilmformer(
                model,
                batches,
                batches,
                epochs=2,
                checkpoint_path=path,
            )
            checkpoint = torch.load(path, weights_only=True)
            restored = make_model()
            restored.load_state_dict(checkpoint["model"], strict=True)
            self.assertEqual(len(history), 2)
            self.assertIn("val", history[-1])
            self.assertFalse(model.training)
        self.assertFalse(torch.equal(before_detector, model.Detector.DownstreamTaskHead.weight))
        self.assertFalse(torch.equal(before_regressor, model.Regressor.ProjStats2.weight))


if __name__ == "__main__":
    unittest.main()
