import tempfile
import unittest
from pathlib import Path

import torch

from training.model.NILMFormer.NILMFormer import NILMFormer, NILMFormerConfig
from training.train_nilmformer import nilmformer_loss, run_nilmformer_epoch, train_nilmformer


class TrainNILMFormerTests(unittest.TestCase):
    def test_loss_excludes_missing_and_invalid_labels(self):
        prediction = torch.tensor([[[2.0, 8.0, 4.0, 9.0]]], requires_grad=True)
        target = torch.tensor([[[1.0, float("nan"), 2.0, 0.0]]])
        valid = torch.tensor([[[True, True, True, False]]])
        losses = nilmformer_loss(prediction, target, valid)
        self.assertEqual(int(losses["valid_count"]), 2)
        self.assertAlmostEqual(float(losses["loss"].detach()), 2.5)
        losses["loss"].backward()
        torch.testing.assert_close(prediction.grad, torch.tensor([[[1.0, 0.0, 2.0, 0.0]]]))
        with self.assertRaisesRegex(AssertionError, "không chứa nhãn hợp lệ"):
            nilmformer_loss(prediction, target, torch.zeros_like(valid))
        with self.assertRaisesRegex(AssertionError, "cùng shape"):
            nilmformer_loss(prediction, target[:, :, :1])

    def test_joint_training_validation_and_checkpoint(self):
        torch.manual_seed(11)
        config = NILMFormerConfig(c_out=2, d_model=16, n_head=4, n_encoder_layers=1, dp_rate=0)
        model = NILMFormer(config)
        before = model.DownstreamTaskHead.weight.detach().clone()
        batches = [{"x": torch.randn(2, 9, 16), "power": torch.ones(2, 2, 16)}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "best.pt"
            history = train_nilmformer(model, batches, batches, epochs=2, checkpoint_path=path)
            checkpoint = torch.load(path, weights_only=True)
            restored = NILMFormer(NILMFormerConfig(**checkpoint["model_config"]))
            restored.load_state_dict(checkpoint["model"], strict=True)
            self.assertAlmostEqual(checkpoint["metrics"]["val"]["loss"], min(row["val"]["loss"] for row in history))
        self.assertEqual(len(history), 2)
        self.assertFalse(model.training)
        self.assertFalse(torch.equal(before, model.DownstreamTaskHead.weight))
        # Validation không thay đổi trọng số hoặc thống kê BatchNorm.
        state = {key: value.clone() for key, value in model.state_dict().items()}
        metrics = run_nilmformer_epoch(model, batches, "cpu")
        self.assertTrue(torch.isfinite(torch.tensor(metrics["loss"])))
        for key, value in model.state_dict().items():
            torch.testing.assert_close(value, state[key], rtol=0, atol=0)

    def test_training_without_validation(self):
        model = NILMFormer(NILMFormerConfig(d_model=16, n_head=4, n_encoder_layers=1, dp_rate=0))
        batches = [{"x": torch.randn(2, 9, 8), "power": torch.ones(2, 1, 8)}]
        history = train_nilmformer(model, batches, epochs=1)
        self.assertNotIn("val", history[0])
        with self.assertRaisesRegex(AssertionError, "rỗng"):
            run_nilmformer_epoch(model, [], "cpu")


if __name__ == "__main__":
    unittest.main()
