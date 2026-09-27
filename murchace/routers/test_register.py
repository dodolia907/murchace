import json

import pytest
from starlette.requests import Request

from ..store import startup_and_shutdown_db
from .register import CartSummary, extract_cart_product_ids, place_order


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def init_db(anyio_backend):
    startup_db, shutdown_db = startup_and_shutdown_db
    await startup_db()
    yield
    await shutdown_db()


def build_request_with_signals(method: str, signals: dict) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": "/register",
        "headers": [
            (b"content-type", b"application/json"),
            (b"datastar-request", b"true"),
        ],
        "query_string": b"",
    }
    body_bytes = json.dumps(signals).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


@pytest.mark.anyio
async def test_extract_cart_product_ids():
    req = build_request_with_signals("POST", {"cart": [1, 2, "3", "invalid"]})
    product_ids = await extract_cart_product_ids(req)
    assert product_ids == [1, 2, 3]

    req_empty = build_request_with_signals("POST", {})
    assert await extract_cart_product_ids(req_empty) == []


@pytest.mark.anyio
async def test_cart_summary(init_db):
    summary = await CartSummary.from_product_ids([1, 1, 2])
    assert summary.total_count == 3
    assert 1 in summary.counted_products
    assert summary.counted_products[1].count == 2
    assert 2 in summary.counted_products
    assert summary.counted_products[2].count == 1


@pytest.mark.anyio
async def test_place_order_flow(init_db):
    # Empty cart
    req_empty = build_request_with_signals("POST", {"cart": []})
    res_empty = await place_order(req_empty)
    assert res_empty.status_code == 200

    # Cart with items
    req = build_request_with_signals("POST", {"cart": [1, 2]})
    res = await place_order(req)
    assert res.status_code == 200
