from scripts.replay_refit import take_replay_lock


async def test_a_second_replay_is_refused_while_the_first_runs(scratch_engine):
    async with scratch_engine.connect() as first, scratch_engine.connect() as second:
        assert await take_replay_lock(first)
        assert not await take_replay_lock(second)
