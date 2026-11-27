import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


def timestamp_features(index: pd.DatetimeIndex) -> np.ndarray:
    # L timestamp → (8, L), mỗi biến gồm sin rồi cos theo đúng thứ tự TimeRPE.
    values = [index.minute.to_numpy(), index.hour.to_numpy(), index.day_of_week.to_numpy(), index.month.to_numpy()]
    periods = [60.0, 24.0, 7.0, 12.0]
    return np.stack([fn(2 * np.pi * value / period) for value, period in zip(values, periods, strict=True) for fn in (np.sin, np.cos)]).astype("float32")


class REFITCSVDataset(Dataset):
    def __init__(self, processed_dir: str | Path, split: str, house_id: int | None = None, normalize: bool = True):
        self.processed_dir = Path(processed_dir)
        self.manifest = json.loads((self.processed_dir / "manifest.json").read_text(encoding="utf-8"))
        assert self.manifest["config"].get("storage_format") == "csv", "Manifest phải trỏ đến dữ liệu CSV đã tiền xử lý."
        assert split in {"train", "test"}, "Tập dữ liệu phải là train hoặc test."
        self.targets = self.manifest["target_channels"]
        self.length = self.manifest["config"]["window_size"]
        self.scale = float(self.manifest["config"]["power_scale_w"]) if normalize else 1.0
        assert self.scale > 0, "Hệ số chuẩn hóa phải lớn hơn 0."
        self.shards = [row for row in self.manifest["shards"] if row["split"] == split and (house_id is None or row["house"] == house_id) and row["windows"] > 0]
        assert self.shards, "Không có dữ liệu CSV phù hợp với tập và hộ được chọn."
        self.ends = np.cumsum([row["windows"] for row in self.shards])
        # Mỗi CSV được đọc một lần cho mỗi đối tượng dataset; tránh đọc lại cả file khi shuffle giữa các hộ.
        self.cached: dict[int, dict[str, np.ndarray]] = {}

    def __len__(self) -> int:
        return int(self.ends[-1])

    def _load_shard(self, shard_index: int) -> dict[str, np.ndarray]:
        shard = self.shards[shard_index]
        frame = pd.read_csv(self.processed_dir / shard["file"], parse_dates=["timestamp"])
        windows, length, channels = shard["windows"], self.length, len(self.targets)
        assert len(frame) == windows * length, "Số dòng CSV không khớp số cửa sổ trong manifest."
        assert np.all(frame["house_id"].to_numpy() == shard["house"]), "CSV chứa dữ liệu của hộ khác manifest."
        assert np.array_equal(frame["window_id"].to_numpy(), np.repeat(np.arange(windows), length)), "Thứ tự window_id trong CSV không hợp lệ."
        assert np.array_equal(frame["step"].to_numpy(), np.tile(np.arange(length), windows)), "Các bước thời gian trong cửa sổ không đúng thứ tự."
        timestamps = pd.DatetimeIndex(frame["timestamp"])
        # (N * L,) → (N, L); kiểm tra mỗi cửa sổ có nhịp liên tục 60 giây.
        time_ns = timestamps.to_numpy(dtype="datetime64[ns]").astype("int64").reshape(windows, length)
        assert (np.diff(time_ns, axis=1) == 60 * 10**9).all(), "Timestamp trong cửa sổ không liên tục theo phút."
        valid_values = frame[[f"{name}_valid" for name in self.targets]].to_numpy()
        assert np.isin(valid_values, [0, 1]).all(), "Mask hợp lệ trong CSV phải bằng 0 hoặc 1."
        valid = valid_values.astype(bool)
        power = frame[[f"{name}_w" for name in self.targets]].to_numpy(dtype="float32")
        on = frame[[f"{name}_on" for name in self.targets]].to_numpy(dtype="float32")
        assert np.isfinite(power[valid]).all() and (power[valid] >= 0).all(), "Công suất có nhãn hợp lệ phải hữu hạn và không âm."
        assert np.isin(on[valid], [0, 1]).all(), "Trạng thái bật/tắt có nhãn hợp lệ phải bằng 0 hoặc 1."
        # CSV giữ ô trống cho kênh thiếu; thay 0 chỉ trong tensor, sau khi đã đọc mask.
        power = np.where(valid, power, 0) / self.scale
        on = np.where(valid, on, 0)
        aggregate = frame["aggregate_w"].to_numpy(dtype="float32") / self.scale
        assert np.isfinite(aggregate).all(), "Điện tổng trong CSV phải hữu hạn."
        encoding = timestamp_features(timestamps)  # (8, N * L)
        # Điện tổng (N, 1, L) + mã thời gian (N, 8, L) → (N, 9, L).
        x = np.concatenate([aggregate.reshape(windows, 1, length), encoding.reshape(8, windows, length).transpose(1, 0, 2)], axis=1)
        return {
            "x": x.astype("float32"),
            "power": power.reshape(windows, length, channels).transpose(0, 2, 1).astype("float32"),
            "on": on.reshape(windows, length, channels).transpose(0, 2, 1).astype("float32"),
            "valid": valid.reshape(windows, length, channels).transpose(0, 2, 1),
            "start_time_ns": time_ns[:, 0],
        }

    def __getitem__(self, index: int) -> dict[str, torch.Tensor | int]:
        assert 0 <= index < len(self), "Chỉ số cửa sổ nằm ngoài tập dữ liệu."
        shard_index = int(np.searchsorted(self.ends, index, side="right"))
        local_index = index - (int(self.ends[shard_index - 1]) if shard_index else 0)
        if shard_index not in self.cached:
            self.cached[shard_index] = self._load_shard(shard_index)
        shard = self.cached[shard_index]
        return {
            **{key: torch.from_numpy(shard[key][local_index].copy()) for key in ("x", "power", "on", "valid")},
            "house_id": self.shards[shard_index]["house"],
            "start_time_ns": int(shard["start_time_ns"][local_index]),
        }
