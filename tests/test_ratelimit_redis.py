"""Rate limiting through a real Redis server (what production uses with more than one replica).

The rest of the suite uses in-memory storage. This test runs only when ``TEST_REDIS_URL`` is set (CI starts a Redis
service) and guards the combination Flask-Limiter + limits + the redis client, which must stay within the versions the
``limits`` package supports.
"""

import os

import pytest

from lumieree import create_app
from lumieree.auth import create_user
from lumieree.config import TestingConfig
from lumieree.extensions import db
from tests.conftest import PASSWORD, Browser

REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="needs a Redis server (set TEST_REDIS_URL)")


def test_login_rate_limit_is_enforced_through_redis():
    import redis

    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()  # limiter counters from earlier runs would skew the count

    class RedisConfig(TestingConfig):
        RATELIMIT_STORAGE_URI = REDIS_URL
        LOGIN_RATE_LIMIT = "3 per minute"

    app = create_app(RedisConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()
        try:
            create_user("redis-user", PASSWORD, role="staff")
            browser = Browser(app)
            statuses = [browser.login("redis-user", "wrong password entirely").status_code for _ in range(4)]
            assert statuses[:3] == [200, 200, 200]  # wrong password re-renders the form
            assert statuses[3] == 429  # the 4th attempt within the minute is refused by the Redis-backed limiter
            assert client.dbsize() > 0  # the counters really live in Redis
        finally:
            db.session.remove()
            db.drop_all()
            client.flushdb()
