import argparse
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch

from training.data import REFITCSVDataset
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageOutput
from training.tests.test_twostage_nilmformer import make_model
from training.train_twostage_nilmformer import (
    TwoStageLossConfig,
    detector_class_weights,
    ensemble_outputs,
    error_analysis_rows,
    house_metric_rows,
    run_study,
    stratified_rows,
    summarize_study,
    temporal_validation_indices,
    train_twostage_nilmformer,
    two_stage_loss,
)


class TwoStageStudyTests(unittest.TestCase):
    def test_per_device_bce_weights_keep_channel_alignment_after_mask(self):
        logits = torch.zeros(1, 2, 2, requires_grad=True)
        power = torch.ones_like(logits)
        output = TwoStageOutput(logits, logits.sigmoid(), power, power, power)
        on = torch.tensor([[[1.0, 0.0], [1.0, 1.0]]])
        valid = torch.tensor([[[True, True], [True, False]]])
        loss = two_stage_loss(output, power, on, valid, TwoStageLossConfig(regression_weight=0, auxiliary_on_weight=0, positive_weight=[2.0, 5.0]))
        self.assertAlmostEqual(float(loss["loss"].detach()), 8 * math.log(2) / 3, places=6)
        loss["loss"].backward()
        torch.testing.assert_close(logits.grad, torch.tensor([[[-1 / 3, 1 / 6], [-5 / 6, 0.0]]]))

    def test_temporal_validation_and_class_counts_exclude_future_labels(self):
        dataset = object.__new__(REFITCSVDataset)
        dataset.targets = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
        dataset.length = 2
        dataset.shards = [{"house": 1, "windows": 10}]
        dataset.manifest = {"config": {"sampling_seconds": 60}, "time_splits": {"1": {"start": "2023-01-01", "train_end_exclusive": "2023-01-01 00:18"}}}
        starts = pd.date_range("2023-01-01", periods=10, freq="2min").to_numpy(dtype="datetime64[ns]").astype("int64")
        on = np.zeros((10, 4, 2), dtype="float32")
        on[0, 0, 0] = 1
        on[8:, 0] = 1
        on[:7, 3] = 1
        valid = np.ones_like(on, dtype=bool)
        valid[:, 2] = False
        dataset.cached = {0: {"start_time_ns": starts, "on": on, "valid": valid}}
        train, validation, rows = temporal_validation_indices(dataset)
        self.assertEqual(train[1], list(range(7)))
        self.assertEqual(validation[1], [8, 9])
        self.assertEqual(rows[0]["boundary_windows_dropped"], 1)
        weights, balance = detector_class_weights(dataset, train[1])
        self.assertEqual(balance[0]["on_count"], 1)
        self.assertEqual(balance[0]["off_count"], 13)
        self.assertEqual(weights[0], 7)
        self.assertFalse(balance[1]["has_positive_train_labels"])
        self.assertFalse(balance[2]["has_train_labels"])
        self.assertAlmostEqual(weights[3], 1 / 15)

    def test_early_stopping_restores_best_and_preserves_last_checkpoint(self):
        model = make_model()
        epoch = 0
        scores = [0.5, 0.4, 0.41, 0.42, 0.43]

        def fake_epoch(model, batches, device, config, optimizer=None, grad_clip=1, metrics_config=None, progress_callback=None):
            nonlocal epoch
            if optimizer is not None:
                epoch += 1
                with torch.no_grad():
                    model.Regressor.ProjStats2.bias.fill_(epoch)
            value = 1.0 if optimizer is not None else scores[epoch - 1]
            return {"loss": value, "regression": value, "detector": 0.0, "auxiliary_on": 0.0}

        with tempfile.TemporaryDirectory() as tmp, patch("training.train_twostage_nilmformer.run_two_stage_epoch", side_effect=fake_epoch):
            path = Path(tmp)
            history = train_twostage_nilmformer(model, [{}], [{}], epochs=10, patience=2, checkpoint_path=path / "best.pt", last_checkpoint_path=path / "last.pt")
            best = torch.load(path / "best.pt", weights_only=True)
            last = torch.load(path / "last.pt", weights_only=True)
            self.assertEqual(len(history), 4)
            self.assertTrue(history[-1]["stopped_early"])
            self.assertEqual(best["best_epoch"], 2)
            self.assertEqual(last["epoch"], 4)
            torch.testing.assert_close(model.Regressor.ProjStats2.bias, torch.full((2,), 2.0))
            torch.testing.assert_close(last["model"]["Regressor.ProjStats2.bias"], torch.full((2,), 4.0))

    def test_cross_house_models_are_tested_on_unseen_houses(self):
        targets = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
        windows, length = 10, 8
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shards, time_splits = [], {}
            for house in (1, 2):
                time_splits[str(house)] = {"start": "2023-01-01", "train_end_exclusive": "2023-01-01 01:20"}
                for split, start in (("train", "2023-01-01"), ("test", "2023-01-01 01:20")):
                    count = windows * length
                    frame = pd.DataFrame(
                        {
                            "house_id": house,
                            "window_id": np.repeat(np.arange(windows), length),
                            "step": np.tile(np.arange(length), windows),
                            "timestamp": pd.date_range(start, periods=count, freq="1min"),
                            "aggregate_w": 3000.0,
                            **{f"{name}_w": np.tile([0.0, 2000.0], count // 2) for name in targets},
                            **{f"{name}_on": np.tile([0, 1], count // 2) for name in targets},
                            **{f"{name}_valid": 1 for name in targets},
                        }
                    )
                    file = f"{split}_house_{house:02d}.csv"
                    frame.to_csv(root / file, index=False)
                    shards.append({"split": split, "house": house, "windows": windows, "file": file})
            manifest = {
                "config": {"storage_format": "csv", "window_size": length, "power_scale_w": 10000, "sampling_seconds": 60},
                "target_channels": targets,
                "thresholds_w": {name: [20] for name in targets},
                "time_splits": time_splits,
                "shards": shards,
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            for model in ("twostage", "nilmformer"):
                with self.subTest(model=model):
                    self.check_study_outputs(root, model)

    def check_study_outputs(self, root: Path, model: str):
        args = argparse.Namespace(
            model=model,
            data_dir=str(root),
            output_dir=str(root / f"run_{model}"),
            epochs=1,
            patience=1,
            min_delta=0.0,
            batch_size=4,
            lr=1e-4,
            num_seeds=1,
            validation_fraction=0.2,
            max_positive_weight=100.0,
            auxiliary_on_weight=0.1,
            device="cpu",
            cpu_threads=1,
            houses=[1, 2],
            protocols=["pooled", "cross_house"],
            smoke_test=True,
        )
        output_dir = run_study(args)
        results = pd.read_csv(output_dir / "test_metrics.csv")
        self.assertEqual(results["model"].unique().tolist(), ["TwoStageNILMFormer" if model == "twostage" else "NILMFormer"])
        self.assertEqual("detector_f1" in results, model == "twostage")
        # Mỗi lượt train có bảng phân tầng, phân tích lỗi và đồ thị dự đoán cho từng hộ test.
        for name in ("seed_test_metrics.csv", "stratified_metrics.csv", "error_analysis.csv", "macro_summary.csv", "stratified_summary.csv", "error_summary.csv"):
            self.assertTrue((output_dir / name).exists(), name)
        # Đồ thị ensemble các seed: ba nhóm mô hình × hai hộ test.
        self.assertEqual(len(list(output_dir.glob("*/predictions/house_*.png"))), 6)
        cross = results[results["protocol"] == "cross_house"]
        # Hai mô hình riêng × hai hộ test × bốn thiết bị; mỗi mô hình gặp đúng một hộ chưa thấy.
        self.assertEqual(len(cross), 16)
        self.assertEqual(sorted(cross[cross["unseen_house"]].groupby("train_houses")["house"].first().tolist()), [1, 2])
        self.assertTrue((cross["unseen_house"] == (cross["train_houses"].astype(str) != cross["house"].astype(str))).all())
        # Mô hình chung train trên nửa số hộ và vẫn được test trên mọi hộ; hộ còn lại là hộ chưa thấy.
        pooled = results[results["protocol"] == "pooled"]
        self.assertEqual(pooled["train_houses"].astype(str).unique().tolist(), ["2"])
        self.assertEqual(sorted(pooled[pooled["unseen_house"]]["house"].unique().tolist()), [1])
        self.assertEqual(sorted(pooled["house"].unique().tolist()), [1, 2])

    def test_stratified_and_error_tables_count_concurrent_devices(self):
        targets = ["A", "B"]
        # Một cửa sổ (N=1), hai thiết bị (C=2), bốn phút (L=4).
        on = torch.tensor([[[1.0, 1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 1.0]]])
        valid = torch.ones_like(on, dtype=torch.bool)
        predicted_on = torch.tensor([[[True, False, True, False], [True, False, False, True]]])
        tensors = {
            "prediction": predicted_on.float() * 100,
            "power": on * 100,
            "on": on,
            "valid": valid,
            "predicted_on": predicted_on,
            "aggregate": torch.tensor([[200.0, 600.0, 100.0, 4000.0]]),
        }
        strata = pd.DataFrame(stratified_rows(tensors, targets, 60)).set_index(["stratum_type", "stratum", "device"])
        # Phút 0 có hai thiết bị bật; phút 1 và 3 có một; phút 2 không có.
        self.assertEqual(strata.loc[("concurrent_on", "2", "A"), "valid_count"], 1)
        self.assertEqual(strata.loc[("concurrent_on", "1", "A"), "valid_count"], 2)
        self.assertEqual(strata.loc[("concurrent_on", "0", "A"), "fp"], 1)
        self.assertEqual(strata.loc[("concurrent_on", "1", "A"), "fn"], 1)
        self.assertEqual(strata.loc[("concurrent_on", "3+", "A"), "valid_count"], 0)
        self.assertEqual(strata.loc[("load_w", "[0, 500)", "A"), "valid_count"], 2)
        self.assertEqual(strata.loc[("load_w", "[3000, inf)", "B"), "tp"], 1)
        errors = pd.DataFrame(error_analysis_rows(tensors, targets)).set_index(["device", "error_type", "context"])
        # FN của A ở phút 1, khi B tắt; FP của A ở phút 2, khi B cũng tắt.
        self.assertEqual(errors.loc[("A", "FN", "Không thiết bị đích khác bật"), "error_points"], 1)
        self.assertEqual(errors.loc[("A", "FN", "B"), "error_points"], 0)
        self.assertEqual(errors.loc[("A", "FP", "Không thiết bị đích khác bật"), "share"], 1.0)
        self.assertEqual(errors.loc[("B", "FP", "A"), "error_total"], 0)

    def test_metrics_are_computed_once_on_seed_ensemble(self):
        # Một cửa sổ (N=1), một thiết bị (C=1), hai phút (L=2); thiết bị bật cả hai phút.
        base = {
            "power": torch.tensor([[[100.0, 100.0]]]),
            "on": torch.ones(1, 1, 2),
            "valid": torch.ones(1, 1, 2, dtype=torch.bool),
            "aggregate": torch.tensor([[300.0, 300.0]]),
            "start_time_ns": torch.tensor([0]),
        }
        outputs = [
            {**base, "prediction": torch.tensor([[[30.0, 0.0]]]), "detector_on": torch.tensor([[[True, False]]])},
            {**base, "prediction": torch.tensor([[[0.0, 30.0]]]), "detector_on": torch.tensor([[[True, True]]])},
        ]
        seed_f1 = [house_metric_rows(dict(output), ["A"], [20.0], 60)[0]["f1"] for output in outputs]
        ensemble = ensemble_outputs(outputs)
        torch.testing.assert_close(ensemble["prediction"], torch.tensor([[[15.0, 15.0]]]))
        # Bỏ phiếu mask: phút 1 có một trên hai seed bật, đủ một nửa nên tính là bật.
        self.assertTrue(ensemble["detector_on"].all())
        row = house_metric_rows(ensemble, ["A"], [20.0], 60)[0]
        # Mỗi seed riêng có F1 = 2/3, nhưng dự đoán ensemble 15 W dưới ngưỡng 20 W nên F1 = 0; không lấy trung bình F1 các seed.
        self.assertEqual(seed_f1, [2 / 3, 2 / 3])
        self.assertEqual(row["f1"], 0.0)
        self.assertEqual(row["detector_f1"], 1.0)

    def test_summary_macro_over_house_pairs(self):
        base = {"model": "M", "protocol": "cross_house", "train_houses": "1", "device": "A", "unseen_house": True}
        # Hộ 4 có quá ít phút bật trong test nên phải bị loại khỏi mọi bảng tổng hợp.
        rows = [{**base, "house": 2, "f1": 0.2, "on_count": 100, "low_support": False}, {**base, "house": 3, "f1": 0.6, "on_count": 100, "low_support": False}]
        rows.append({**base, "house": 4, "f1": 0.0, "on_count": 4, "low_support": True})
        strata = [
            {**row, "stratum_type": "concurrent_on", "stratum": "1", "mae_w": 1.0, "relative_energy_error": 0.1, "precision": 1.0, "recall": 1.0, "valid_count": 4, "on_count": 2} for row in rows
        ]
        errors = [{**base, "house": house, "error_type": "FP", "context": "B", "error_points": points, "error_total": 10, "low_support": house == 4} for house, points in ((2, 2), (3, 6), (4, 9))]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            summarize_study(rows, strata, errors, output_dir)
            macro = pd.read_csv(output_dir / "macro_summary.csv")
            self.assertAlmostEqual(macro.loc[0, "f1_mean"], 0.4)
            self.assertAlmostEqual(macro.loc[0, "f1_median"], 0.4)
            self.assertEqual(macro.loc[0, "f1_count"], 2)
            self.assertEqual(pd.read_csv(output_dir / "low_support_pairs.csv")["house"].tolist(), [4])
            self.assertAlmostEqual(pd.read_csv(output_dir / "stratified_summary.csv").loc[0, "f1_mean"], 0.4)
            error = pd.read_csv(output_dir / "error_summary.csv")
            # Cộng số điểm lỗi hai hộ (2 + 6) trên tổng (10 + 10) trước khi chia.
            self.assertEqual(error.loc[0, "error_points"], 8)
            self.assertAlmostEqual(error.loc[0, "share"], 0.4)


if __name__ == "__main__":
    unittest.main()
