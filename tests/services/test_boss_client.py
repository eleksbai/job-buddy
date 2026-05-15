import asyncio

from job_buddy.core.boss import LocalBossStubClient


def test_local_boss_stub_search_jobs():
    client = LocalBossStubClient()
    jobs = asyncio.run(client.search_jobs({"keywords": ["Python"], "city": "Shanghai"}))

    assert len(jobs) >= 1
    assert jobs[0]["company"]
