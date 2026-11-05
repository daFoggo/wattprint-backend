# NILM replay: a REFIT day through the model, minute by minute

Demo of the pipeline *meter data -> NILMFormer -> per-appliance power -> API*, using one REFIT
house instead of a live meter. It reuses the energy schema of `database-design.md`; it adds no
table and no migration.

## What happens

`POST /api/v1/simulations {"date": "2015-01-05"}` starts a background replay of that REFIT day
(UTC, as in the CSV) for the REFIT home of the signed-in account. The home, its meter, devices
and series are created on first use by `provision_house`. For every minute of the day:

1. the minute is read from `CLEAN_House<N>.csv` (10 s mean, ffill, clip, 1 min mean: the training
   preprocessing),
2. the aggregate (`Aggregate`) and the plug sub-meters of the tracked appliances go through
   `ingest_readings`, into `energy.reading` (kind `main` and `plug`),
3. the model runs on the last 256 minutes of aggregate power (the first minutes of the day use
   the previous day as context),
4. the estimate of the last minute goes through `ingest_estimates`, into
   `energy.device_estimate` (series of kind `device`, created per appliance on first use), tagged
   with the `energy.inference_run` row of the replay (`NILMFormer` / `custom0`).

Each minute is committed, so the readers below show the day growing. Tracked appliances are
those of the home with a checkpoint: `kettle`, `microwave`, `dishwasher`, `washing_machine`
(`app/ml/__init__.py`). The sub-meter of the same device is the ground truth for the accuracy.

## Endpoints (all need the Bearer token of the account)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/simulations` | start a replay (`date`, `house`, `replay_date`, `rows_per_second`); 202 |
| `GET /api/v1/simulations/{id}` | status, progress, error |
| `DELETE /api/v1/simulations/{id}` | stop after the current minute; stored data is kept |
| `GET /api/v1/simulations/{id}/result` | disaggregation of the replayed day (partial while running) |
| `GET /api/v1/disaggregation?date=&period=day\|week` | kWh per appliance + `other`, hourly/daily points |
| `GET /api/v1/disaggregation/latest?minutes=N` | newest minutes: aggregate, estimates, sub-meters, `error_w` |

`id` is the `run_id` of `energy.inference_run`. `error_w` is the sub-meter reading minus the
estimate in W (positive: the model under-estimates). `accuracy_pct` is
`100 * (1 - sum|estimate - truth| / (2 * sum truth))` per minute; `energy_error_pct` compares the
kWh. Both need the sub-meter, so they are absent for homes without one.

## Timestamps: the replay day is moved to a recent day

`energy.reading` and `energy.device_estimate` drop data older than 400 days and the 1-minute
continuous aggregate only refreshes the last 7 days (`ops.set_policies`). REFIT is from
2013-2015, so the day is stored under `replay_date` (default yesterday, at most 6 days back):
`stored_ts = csv_ts + shift`, where the shift maps 00:00 UTC of the REFIT day to 00:00
Asia/Ho_Chi_Minh of `replay_date` (`replay_shift`). The stored day then lines up with the local
days of the aggregates and of `app/services/meter.py`. The model features (hour, weekday, month)
use the original clock. Replaying a day again replaces the data of the same home and
`replay_date`.

## Running it

The API image needs PyTorch and three things from outside the repository (all git-ignored):

| Input | Where | Env (see `.env.example`) |
|---|---|---|
| REFIT CSVs | `dataset/` | `REFIT_DIR`, `REFIT_CSV_DIR` |
| NILMFormer source | `third_party/NILMFormer/` | `NILM_REPO_DIR` |
| checkpoints `NILMFormer_custom0_*.pt` | `checkpoints/` | `NILM_CKPT_HOST_DIR` |

```bash
# .env: COMPOSE_FILE=docker-compose.yml:docker-compose.nilm.yml          (CPU)
#       COMPOSE_FILE=docker-compose.yml:docker-compose.nilm.yml:docker-compose.gpu.yml   (NVIDIA)
docker compose up -d --build
```

Then, in Swagger (`/docs`): register (`POST /auth/register`), Authorize with that email and
password, `POST /simulations`, follow `GET /simulations/{id}`, read the result.

PyTorch comes from the `cpu` or `gpu` extra of `pyproject.toml` (`TORCH_EXTRA`, baked at build
time). The job runs inside the API process: restarting the API (or `--reload` on a code change)
stops a running replay; its run is then marked `failed`. One replay at a time per home.

## Limits

* The model is a demo checkpoint trained on REFIT house 2; other houses give poor estimates.
* One `ops.ingest_batch` row is written per replayed minute (one batch per `ingest_readings`
  call), about 1440 per day.
* Report and `latest` read the raw hypertables for the accuracy and the minute view, over a week
  at most.
* The SQL of the services is covered by the manual walk-through above, not by DB tests yet.
