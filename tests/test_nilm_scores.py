from app.modules.nilm.services.scores import scores_from

SIDECAR = {
    "labels": ["Fridge", "Microwave", "Kettle"],
    "meta": {
        "test_from": "2015-01-24 19:38:30",
        "test_by_device": {
            "Fridge": {"energy F1": 0.622, "kWh err %": 3.59, "F1 ON/OFF": 0.744},
            "Microwave": {"energy F1": 0.466, "kWh err %": -13.35, "F1 ON/OFF": 0.629},
            "Kettle": {"energy F1": 0.834, "kWh err %": 0.24, "F1 ON/OFF": 0.909},
        },
    },
}


def test_each_device_type_gets_its_held_out_score_and_a_level():
    got = scores_from(SIDECAR)
    assert set(got) == {"fridge_freezer", "microwave", "kettle"}
    assert got["kettle"].level == "high"  # energy F1 >= 0.7
    assert got["fridge_freezer"].level == "medium"  # >= 0.5
    assert got["microwave"].level == "low"
    assert got["microwave"].kwh_err_pct == -13.35
    assert got["microwave"].energy_f1 == 0.466


def test_a_bundle_never_scored_has_no_scores():
    assert scores_from({"labels": ["Fridge"], "meta": {}}) == {}


async def test_the_home_reads_the_sidecar_of_the_model_the_worker_runs(tmp_path, monkeypatch):
    # The home's active model (runner.TARGETS' query) gives the .pt's .json sidecar; a home whose
    # model has no sidecar gets no scores.
    import json
    import uuid

    from sqlalchemy import text

    from app.config import settings
    from app.database import SessionLocal
    from app.modules.nilm.api import device_scores

    (tmp_path / "own").mkdir()
    doc = {**SIDECAR, "meta": {"test_by_device": {"Kettle": {**_KETTLE, "energy F1": 0.8}}}}
    (tmp_path / "own" / "nilm_pipeline.json").write_text(json.dumps(doc))
    monkeypatch.setattr(settings, "nilm_model_dir", str(tmp_path))
    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as s, s.begin():
        own = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('A') RETURNING id"))
        bare = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('B') RETURNING id"))
        await s.execute(
            text(
                "INSERT INTO public.tb_nilm_model (home_id, name, version, artifact, active) "
                "VALUES (:h, 'm', :v, 'own/nilm_pipeline.pt', true), "
                "(:b, 'm', :v, 'missing/nilm_pipeline.pt', true)"
            ),
            {"h": own, "b": bare, "v": tag},
        )
    try:
        async with SessionLocal() as s:
            assert (await device_scores(s, own))["kettle"].energy_f1 == 0.8
            assert await device_scores(s, bare) == {}
    finally:
        async with SessionLocal() as s, s.begin():  # the models go with their homes (cascade)
            await s.execute(
                text("DELETE FROM public.tb_home WHERE id IN (:a, :b)"), {"a": own, "b": bare}
            )


_KETTLE = {"energy F1": 0.834, "kWh err %": 0.24, "F1 ON/OFF": 0.909}
