from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_db_session
from app.core.security import create_access_token, hash_password
from app.db.session import Base
from app.main import app
from app.models.address import Address
from app.models.notification import Notification
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payout_request import PayoutRequest
from app.models.product import Product
from app.models.user import User
from app.models.vendor import Vendor, VendorPromotion


@pytest_asyncio.fixture
async def vendor_test_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        vendor_a = Vendor(
            name="Vendor A", slug="vendor-a", email="a@example.com", hashed_password=hash_password("VendorPass123"),
            role="vendor", category="Food", description="Vendor A description", city="Johannesburg",
            is_active=True, is_onboarded=True, is_approved=True, bank_name="Test Bank",
            bank_account_name="Vendor A", bank_account="1234567890",
        )
        vendor_b = Vendor(
            name="Vendor B", slug="vendor-b", email="b@example.com", hashed_password=hash_password("VendorPass123"),
            role="vendor", category="Retail", description="Vendor B description", city="Pretoria",
            is_active=True, is_onboarded=True, is_approved=True, bank_name="Test Bank",
            bank_account_name="Vendor B", bank_account="9876543210",
        )
        customer = User(
            full_name="Test Customer", email="customer@example.com", hashed_password=hash_password("CustomerPass123"),
            role="customer", is_active=True,
        )
        session.add_all([vendor_a, vendor_b, customer])
        await session.flush()

        product_a = Product(
            vendor_id=vendor_a.id, name="Product A", description="Product A description",
            price=100, category="Food", prep_time_minutes=15, stock_quantity=10, is_available=True,
        )
        product_b = Product(
            vendor_id=vendor_b.id, name="Product B", description="Product B description",
            price=200, category="Retail", prep_time_minutes=15, stock_quantity=10, is_available=True,
        )
        address = Address(
            user_id=customer.id, label="Home", recipient_name=customer.full_name,
            line1="1 Test Street", city="Johannesburg", state="Gauteng", latitude=-26.2, longitude=28.0,
        )
        session.add_all([product_a, product_b, address])
        await session.flush()

        order_a = Order(
            order_reference="QD-A", user_id=customer.id, vendor_id=vendor_a.id, address_id=address.id,
            status=OrderStatus.pending, subtotal_amount=100, delivery_fee=20, total_amount=120,
            payment_method="cash_on_delivery", payment_status="paid",
        )
        order_b = Order(
            order_reference="QD-B", user_id=customer.id, vendor_id=vendor_b.id, address_id=address.id,
            status=OrderStatus.pending, subtotal_amount=200, delivery_fee=20, total_amount=220,
            payment_method="cash_on_delivery", payment_status="paid",
        )
        delivered_a = Order(
            order_reference="QD-A-DELIVERED", user_id=customer.id, vendor_id=vendor_a.id, address_id=address.id,
            status=OrderStatus.delivered, subtotal_amount=100, delivery_fee=20, total_amount=120,
            payment_method="cash_on_delivery", payment_status="paid",
        )
        session.add_all([order_a, order_b, delivered_a])
        await session.flush()
        session.add_all([
            OrderItem(order_id=order_a.id, product_id=product_a.id, quantity=1, unit_price=100, total_price=100),
            OrderItem(order_id=order_b.id, product_id=product_b.id, quantity=1, unit_price=200, total_price=200),
            OrderItem(order_id=delivered_a.id, product_id=product_a.id, quantity=1, unit_price=100, total_price=100),
            VendorPromotion(vendor_id=vendor_a.id, product_id=product_a.id, promo_type="seasonal_discount", title="A Promo", description="Vendor A promotion", status="approved"),
            VendorPromotion(vendor_id=vendor_b.id, product_id=product_b.id, promo_type="seasonal_discount", title="B Promo", description="Vendor B promotion", status="pending"),
            PayoutRequest(requester_role="vendor", requester_vendor_id=vendor_a.id, requester_name=vendor_a.name, requester_email=vendor_a.email, amount=10, bank_name="Test Bank", account_name=vendor_a.name, account_number=vendor_a.bank_account),
            Notification(recipient_role="vendor", recipient_vendor_id=vendor_a.id, title="A Notice", message="For Vendor A", category="order"),
            Notification(recipient_role="vendor", recipient_vendor_id=vendor_b.id, title="B Notice", message="For Vendor B", category="order"),
        ])
        await session.commit()
        ids = {"a": vendor_a.id, "b": vendor_b.id, "product_a": product_a.id, "product_b": product_b.id, "order_a": order_a.id, "order_b": order_b.id}

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "ids": ids,
            "token_a": create_access_token(str(ids["a"]), "vendor"),
            "token_b": create_access_token(str(ids["b"]), "vendor"),
        }
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def request(context, method, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kwargs)


@pytest.mark.asyncio
async def test_vendor_auth_and_profile_persist(vendor_test_context):
    context = vendor_test_context
    response = await request(context, "POST", "/auth/vendor/login", json={"email": "a@example.com", "password": "VendorPass123"})
    assert response.status_code == 200
    assert response.json()["user"]["id"] == context["ids"]["a"]
    assert (await request(context, "GET", "/vendors/me/profile", context["token_a"])).status_code == 200
    update = await request(context, "PUT", "/vendors/me/profile", context["token_a"], json={"city": "Soweto", "description": "Updated description"})
    assert update.status_code == 200
    profile = (await request(context, "GET", "/vendors/me/profile", context["token_a"])).json()
    assert profile["city"] == "Soweto"
    assert profile["description"] == "Updated description"
    assert (await request(context, "GET", "/vendors/me/profile", "invalid-token")).status_code == 401


@pytest.mark.asyncio
async def test_vendor_isolation_for_products_orders_payouts_promotions_notifications(vendor_test_context):
    context = vendor_test_context
    products_a = (await request(context, "GET", "/products?vendor_id=999&include_unavailable=true", context["token_a"])).json()
    products_b = (await request(context, "GET", "/products?include_unavailable=true", context["token_b"])).json()
    assert {item["name"] for item in products_a} == {"Product A"}
    assert {item["name"] for item in products_b} == {"Product B"}
    assert (await request(context, "PATCH", f"/products/{context['ids']['product_b']}", context["token_a"], json={"name": "Hijacked"})).status_code == 404
    created_product = await request(
        context,
        "POST",
        "/products",
        context["token_a"],
        json={
            "name": "Created Product A",
            "description": "Created product description",
            "price": 55,
            "category": "Food",
            "stock_quantity": 4,
        },
    )
    assert created_product.status_code == 201
    created_product_id = created_product.json()["id"]
    updated_product = await request(context, "PATCH", f"/products/{created_product_id}", context["token_a"], json={"price": 65})
    assert updated_product.status_code == 200
    products_after = (await request(context, "GET", "/products?include_unavailable=true", context["token_a"])).json()
    assert next(item for item in products_after if item["id"] == created_product_id)["price"] == 65

    orders_a = (await request(context, "GET", "/orders/vendor/history", context["token_a"])).json()
    assert {item["order_reference"] for item in orders_a} == {"QD-A", "QD-A-DELIVERED"}
    assert (await request(context, "PATCH", f"/orders/vendor/{context['ids']['order_b']}", context["token_a"], json={"status": "confirmed"})).status_code == 404

    payouts_a = (await request(context, "GET", "/vendors/me/payouts", context["token_a"])).json()
    payouts_b = (await request(context, "GET", "/vendors/me/payouts", context["token_b"])).json()
    assert len(payouts_a["payout_requests"]) == 1
    assert payouts_b["payout_requests"] == []
    payout = await request(context, "POST", "/vendors/me/payout-requests", context["token_a"], json={"amount": 20, "note": "Test payout"})
    assert payout.status_code == 200
    assert len((await request(context, "GET", "/vendors/me/payouts", context["token_a"])).json()["payout_requests"]) == 2

    promos_a = (await request(context, "GET", "/vendors/me/promotions", context["token_a"])).json()
    promos_b = (await request(context, "GET", "/vendors/me/promotions", context["token_b"])).json()
    assert {item["title"] for item in promos_a} == {"A Promo"}
    assert {item["title"] for item in promos_b} == {"B Promo"}
    assert (await request(context, "PATCH", f"/vendors/me/promotions/{promos_b[0]['id']}", context["token_a"], json={"title": "Hijacked"})).status_code == 404
    created_promotion = await request(
        context,
        "POST",
        "/vendors/me/promotions",
        context["token_a"],
        json={"product_id": context["ids"]["product_a"], "promo_type": "best_seller", "title": "Created Promo", "description": "Created promotion"},
    )
    assert created_promotion.status_code == 201

    notifications = (await request(context, "GET", "/notifications/vendor/me", context["token_a"])).json()
    assert [item["title"] for item in notifications] == ["A Notice"]
    read = await request(context, "PATCH", f"/notifications/{notifications[0]['id']}/read", context["token_a"])
    assert read.status_code == 200
    assert (await request(context, "GET", "/notifications/vendor/me", context["token_a"])).json()[0]["is_read"] is True


@pytest.mark.asyncio
async def test_vendor_order_transitions_and_promotion_lifecycle_persist(vendor_test_context):
    context = vendor_test_context
    transition = await request(context, "PATCH", f"/orders/vendor/{context['ids']['order_a']}", context["token_a"], json={"status": "confirmed"})
    assert transition.status_code == 200
    assert (await request(context, "PATCH", f"/orders/vendor/{context['ids']['order_a']}", context["token_a"], json={"status": "delivered"})).status_code == 409
    orders = (await request(context, "GET", "/orders/vendor/history", context["token_a"])).json()
    assert next(item for item in orders if item["id"] == context["ids"]["order_a"])["status"] == "confirmed"

    promos = (await request(context, "GET", "/vendors/me/promotions", context["token_a"])).json()
    promotion_id = promos[0]["id"]
    edited = await request(context, "PATCH", f"/vendors/me/promotions/{promotion_id}", context["token_a"], json={"title": "Updated A Promo"})
    assert edited.status_code == 409
    active = await request(context, "PATCH", f"/vendors/me/promotions/{promotion_id}/status", context["token_a"], json={"status": "active"})
    assert active.status_code == 200
    inactive = await request(context, "PATCH", f"/vendors/me/promotions/{promotion_id}/status", context["token_a"], json={"status": "inactive"})
    assert inactive.status_code == 200
    edited = await request(context, "PATCH", f"/vendors/me/promotions/{promotion_id}", context["token_a"], json={"title": "Updated A Promo"})
    assert edited.status_code == 200
    persisted = (await request(context, "GET", "/vendors/me/promotions", context["token_a"])).json()
    assert next(item for item in persisted if item["id"] == promotion_id)["title"] == "Updated A Promo"


@pytest.mark.asyncio
async def test_vendor_websocket_authorization(vendor_test_context):
    context = vendor_test_context
    with TestClient(app) as client:
        with client.websocket_connect(f"/orders/ws?token={context['token_a']}&order_id={context['ids']['order_a']}") as websocket:
            assert websocket.receive_json()["event"] == "order.bootstrap"
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/orders/ws?token={context['token_b']}&order_id={context['ids']['order_a']}"):
                pass
        assert error.value.code == 4403
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/orders/ws?token=invalid-token&order_id={context['ids']['order_a']}"):
                pass
        assert error.value.code == 4401