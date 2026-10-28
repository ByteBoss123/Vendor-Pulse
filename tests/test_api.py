"""API contract tests against temporary, deliberately repeated order items."""
import importlib
import sys
from pathlib import Path
import duckdb
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client(tmp_path, monkeypatch):
    con = duckdb.connect()
    tables = {
        'seller_kpis': "SELECT 's1' seller_id, 'SP' seller_state, 'city' seller_city, 2 order_count, 30.0 total_revenue, 10.0 avg_item_price, 0.6667 on_time_rate, 1.0 avg_delay_days, 4.0 avg_review_score",
        'fact_order_items': "SELECT * FROM (VALUES ('o1','s1',true,0), ('o1','s1',true,0), ('o2','s1',false,3)) t(order_id,seller_id,delivered_on_time,delivery_delay_days)",
        'fact_orders': "SELECT * FROM (VALUES ('o1'), ('o2')) t(order_id)",
        'dim_seller': "SELECT 's1' seller_id, 'SP' seller_state",
    }
    for name, query in tables.items():
        con.sql(query).write_parquet(str(tmp_path / f'{name}.parquet'))
    con.close()
    monkeypatch.setenv('VENDORPULSE_WAREHOUSE', str(tmp_path))
    import config, api
    importlib.reload(config)
    importlib.reload(api)
    with TestClient(api.app) as client:
        yield client


def test_order_count_and_scope_are_consistent(client):
    all_rows = client.get('/kpis/fulfillment').json()
    state_rows = client.get('/kpis/fulfillment?state=SP').json()
    assert all_rows['order_count'] == state_rows['order_count'] == 2
    assert all_rows['on_time_rate'] == pytest.approx(2/3)
    assert client.get('/kpis/fulfillment?state=XX').json()['order_count'] == 0


def test_seller_routes_and_input_validation(client):
    assert client.get('/sellers/top').json()[0]['seller_id'] == 's1'
    assert client.get('/sellers/s1').json()['order_count'] == 2
    assert client.get('/sellers/missing').status_code == 404
    assert client.get('/sellers/top?limit=-1').status_code == 422
    assert client.get('/sellers/top?sort_by=bad').status_code == 400
