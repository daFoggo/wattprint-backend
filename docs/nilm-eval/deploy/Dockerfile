# Image suy luận NILM chỉ dùng CPU cho 2Stage chung (ensemble 5 seed).
# Build từ thư mục gốc repo: docker build -f deploy/Dockerfile -t wattprint-nilm:cpu .
FROM python:3.14-slim

# Bản PyTorch CPU nhẹ hơn nhiều so với bản CUDA dùng khi train.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 \
 && pip install --no-cache-dir "pandas>=2.2" "numpy>=2.0"

WORKDIR /app
COPY training/data.py training/data.py
COPY training/model/TwoStageNILMFormer training/model/TwoStageNILMFormer
COPY deploy/suy_luan.py deploy/suy_luan.py
COPY deploy/trong_so deploy/trong_so
COPY deploy/vi_du deploy/vi_du

ENTRYPOINT ["python", "deploy/suy_luan.py"]
CMD ["--input", "deploy/vi_du/ho_03_dien_tong.csv", "--output", "/tmp/ket_qua.csv"]
