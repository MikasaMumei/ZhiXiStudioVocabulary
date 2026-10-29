import json
from pathlib import Path
from uuid import uuid4
import sys

import psycopg
import pytest
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from englishwords import create_app


@pytest.fixture
def app():
    settings_path = Path('.local/settings.json')
    if not settings_path.exists():
        pytest.fail('真实 PostgreSQL 测试需要 .local/settings.json；不使用 SQLite 替代。')
    settings = json.loads(settings_path.read_text())
    url = make_url(settings['DATABASE_URL'])
    if url.host not in ('127.0.0.1', 'localhost') or url.port != 55432:
        pytest.fail('集成测试仅允许预定的本机 55432 端口。')
    with psycopg.connect(str(url.set(drivername='postgresql').render_as_string(hide_password=False)), autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname='englishwords_tests'").fetchone():
            connection.execute('CREATE DATABASE englishwords_tests')
    url = url.set(database='englishwords_tests')
    schema = 'ew_test_' + uuid4().hex
    with psycopg.connect(str(url.set(drivername='postgresql').render_as_string(hide_password=False)), autocommit=True) as connection:
        connection.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(schema)))
    settings['DATABASE_URL'] = url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    settings.update(TESTING=True, ADMIN_PASSWORD_HASH=generate_password_hash('test-password'), SECRET_KEY='isolated-test-secret')
    app = create_app(settings)
    result = app.test_cli_runner().invoke(args=['migrate'])
    assert result.exit_code == 0, result.output
    yield app
    app.extensions['engine'].dispose()


@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['authenticated'] = True
    return client
