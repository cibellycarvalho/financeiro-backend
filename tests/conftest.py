import sys
from unittest.mock import MagicMock

# Mock psycopg2 and submodules before importing app
psycopg2_mock = MagicMock()
psycopg2_mock.extras = MagicMock()
psycopg2_pool_mock = MagicMock()
psycopg2_pool_mock.ThreadedConnectionPool = MagicMock()
sys.modules["psycopg2"] = psycopg2_mock
sys.modules["psycopg2.extras"] = psycopg2_mock.extras
sys.modules["psycopg2.pool"] = psycopg2_pool_mock

import pytest
from unittest.mock import patch
from app import create_app

ADMIN_USER = {"user_id": "fd3a3d59-727f-40e2-bbea-c91187d2f0a7", "email": "cibellypeitl63@gmail.com", "fin_role": "fin_admin"}
VIEWER_USER = {"user_id": "aaaabbbb-0000-0000-0000-000000000001", "email": "socio@test.com", "fin_role": "fin_viewer"}

@pytest.fixture
def app():
    with patch("db.get_pool"):
        application = create_app()
        application.config["TESTING"] = True
        yield application

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer fake-admin-token"}

@pytest.fixture
def viewer_headers():
    return {"Authorization": "Bearer fake-viewer-token"}

@pytest.fixture(autouse=True)
def mock_verify_jwt(request, monkeypatch):
    user = ADMIN_USER
    if "viewer" in request.node.name:
        user = VIEWER_USER
    monkeypatch.setattr("auth.verify_jwt", lambda token: user)
