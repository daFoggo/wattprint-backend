FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /code
COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-install-project
# The NILM worker image (compose service `nilm`) adds CPU-only torch; the API image stays without it.
# shortcut: torch comes from the PyTorch CPU index, outside uv.lock (which pins the CUDA build used
# for training); move to a uv index/conflict setup if the versions ever drift.
ARG WITH_NILM=0
RUN if [ "$WITH_NILM" = "1" ]; then \
      uv pip install --python /opt/venv/bin/python --index-url https://download.pytorch.org/whl/cpu \
        "torch==$(uv export --locked --only-group nilm --no-hashes | sed -n 's/^torch==\([0-9.]*\).*/\1/p')"; \
    fi
COPY . .
EXPOSE 11093
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 11093 --timeout-graceful-shutdown 3"]
