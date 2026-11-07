"""NILM model constants shared with the API. Kept free of torch so it can always be imported."""

MODEL_NAME = "NILMFormer"
MODEL_VERSION = "custom0"
WINDOW = 256  # minutes of aggregate power the checkpoints were trained with
# catalog.device_type codes that have a checkpoint (see app/ml/nilm.py CKPT_FILES).
NILM_APPLIANCES = ("kettle", "microwave", "dishwasher", "washing_machine")
