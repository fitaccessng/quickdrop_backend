import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
from app.models.vendor import Vendor


@pytest_asyncio.fixture
async def admin_test_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        admin = User(
            full_name="Admin Test", email="admin@example.com", hashed_password=hash_password("AdminPass123"),
            role="admin", is_active=True,
        )
        customer = User(
            full_name="Customer Test", email="customer@example.com", hashed_password=hash_password("CustomerPass123"),
            role="customer", is_active=True,
        )
        rider = User(
            full_name="Rider Test", email="rider@example.com", hashed_password=hash_password("RiderPass123"),
            role="rider", is_active=True, rider_status="available", current_latitude=-26.2, current_longitude=28.0,
        )
        vendor = Vendor(
            name="Vendor Test", slug="vendor-test", email="vendor@example.com", hashed_password=hash_password("VendorPass123"),
            role="vendor", category="Food", description="Vendor description", city="Johannesburg",
            is_active=True, is_onboarded=True, is_approved=False,
        )
        session.add_all([admin, customer, rider, vendor])
        await session.flush()

        address = Address(
            user_id=customer.id, label="Home", recipient_name=customer.full_name,
            line1="1 Test Street", city="Johannesburg", state="Gauteng", latitude=-26.2, longitude=28.0,
        )
        product = Product(
            vendor_id=vendor.id, name="Test Product", description="A test product description",
            price=100, category="Food", prep_time_minutes=15, stock_quantity=10, is_available=True,
        )
        session.add_all([address, product])
        await session.flush()

        order = Order(
            order_reference="ADMIN-QD-1", user_id=customer.id, vendor_id=vendor.id, address_id=address.id,
            status=OrderStatus.confirmed, subtotal_amount=100, delivery_fee=20, total_amount=120,
            payment_method="cash_on_delivery", payment_status="paid",
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(order_id=order.id, product_id=product.id, quantity=1, unit_price=100, total_price=100)
        )
        payout = PayoutRequest(
            requester_role="vendor", requester_vendor_id=vendor.id, requester_name=vendor.name,
            requester_email=vendor.email, amount=10, status="pending",
        )
        session.add_all([
            payout,
            Notification(recipient_role="admin", recipient_user_id=admin.id, title="Admin notice", message="Admin only", category="system"),
            Notification(recipient_role="admin", recipient_user_id=None, title="Global notice", message="Global admin notice", category="system"),
        ])
        await session.commit()
        ids = {"admin": admin.id, "customer": customer.id, "rider": rider.id, "vendor": vendor.id, "order": order.id, "payout": payout.id}

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        yield {
            "engine": engine,
            "ids": ids,
            "admin_token": create_access_token(str(ids["admin"]), "admin"),
            "customer_token": create_access_token(str(ids["customer"]), "user"),
        }
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def request(context, method, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kwargs)


@pytest.mark.asyncio
async def test_admin_authentication_and_protected_routes(admin_test_context):
    context = admin_test_context
    login = await request(
        context,
        "POST",
        "/auth/unified-login",
        json={"email": "admin@example.com", "password": "AdminPass123"},
    )
    assert login.status_code == 200
    assert login.json()["account_type"] == "admin"
    assert (await request(context, "GET", "/admin/dashboard", context["admin_token"])).status_code == 200
    assert (await request(context, "GET", "/admin/dashboard", context["customer_token"])).status_code == 401
    assert (await request(context, "GET", "/admin/dashboard", "invalid-token")).status_code == 401
    assert (await request(context, "GET", "/admin/dashboard")).status_code == 401


@pytest.mark.asyncio
async def test_admin_reads_real_related_data_and_notification_scope(admin_test_context):
    context = admin_test_context
    dashboard = (await request(context, "GET", "/admin/dashboard", context["admin_token"])).json()
    assert dashboard["total_users"] == 1
    assert dashboard["total_vendors"] == 1
    assert dashboard["total_riders"] == 1
    assert dashboard["active_orders"] == 1

    users = (await request(context, "GET", "/admin/users?role=customer", context["admin_token"])).json()
    riders = (await request(context, "GET", "/admin/riders", context["admin_token"])).json()
    vendors = (await request(context, "GET", "/admin/vendors", context["admin_token"])).json()
    orders = (await request(context, "GET", "/admin/orders?status=all", context["admin_token"])).json()
    assert users[0]["id"] == context["ids"]["customer"]
    assert riders[0]["id"] == context["ids"]["rider"]
    assert vendors[0]["id"] == context["ids"]["vendor"]
    assert orders[0]["id"] == context["ids"]["order"]
    assert orders[0]["vendor_name"] == "Vendor Test"
    assert orders[0]["customer_name"] == "Customer Test"

    notifications = (await request(context, "GET", "/notifications/admin/me", context["admin_token"])).json()
    assert {item["title"] for item in notifications} == {"Admin notice", "Global notice"}


@pytest.mark.asyncio
async def test_admin_mutations_persist_and_validate_authorization(admin_test_context):
    context = admin_test_context
    approval = await request(
        context, "PATCH", f"/admin/vendors/{context['ids']['vendor']}/approval", context["admin_token"], json={"is_approved": True}
    )
    assert approval.status_code == 200
    vendor = (await request(context, "GET", f"/admin/vendors/{context['ids']['vendor']}/analytics", context["admin_token"])).json()
    assert vendor["is_approved"] is True

    assignment = await request(
        context,
        "PATCH",
        f"/admin/orders/{context['ids']['order']}/assign-rider",
        context["admin_token"],
        json={"rider_id": context["ids"]["rider"]},
    )
    assert assignment.status_code == 200
    assert assignment.json()["rider"]["id"] == context["ids"]["rider"]
    refreshed = (await request(context, "GET", f"/admin/orders/{context['ids']['order']}", context["admin_token"])).json()
    assert refreshed["status"] == "rider_assigned"

    payout = await request(
        context, "PATCH", f"/admin/payout-requests/{context['ids']['payout']}", context["admin_token"], json={"status": "approved"}
    )
    assert payout.status_code == 200
    persisted_payout = (await request(context, "GET", "/admin/payout-requests", context["admin_token"])).json()
    assert persisted_payout[0]["status"] == "approved"

    assert (await request(context, "PATCH", f"/admin/orders/{context['ids']['order']}/assign-rider", context["customer_token"], json={"rider_id": context["ids"]["rider"]})).status_code == 401
    assert (await request(context, "PATCH", "/admin/vendors/999/approval", context["admin_token"], json={"is_approved": True})).status_code == 404


@pytest.mark.asyncio
async def test_admin_customer_vendor_status_and_transaction_revenue_queries(admin_test_context):
    context = admin_test_context

    customer_status = await request(
        context,
        "PATCH",
        f"/admin/customers/{context['ids']['customer']}/status",
        context["admin_token"],
        json={"status": "inactive"},
    )
    assert customer_status.status_code == 200
    assert customer_status.json()["is_active"] is False

    vendor_status = await request(
        context,
        "PATCH",
        f"/admin/vendors/{context['ids']['vendor']}/status",
        context["admin_token"],
        json={"status": "suspended"},
    )
    assert vendor_status.status_code == 200
    assert vendor_status.json()["is_active"] is False

    payments = (await request(context, "GET", "/admin/payments", context["admin_token"])).json()
    assert len(payments) >= 1
    assert payments[0]["amount"] >= 0

    revenue = (await request(context, "GET", "/admin/revenue", context["admin_token"])).json()
    assert revenue["gross_revenue"] >= 120
    assert revenue["completed_payment_amount"] >= 0


@pytest.mark.asyncio
async def test_admin_orders_support_search_date_pagination_and_status_mutation(admin_test_context):
    context = admin_test_context

    search_result = (await request(context, "GET", "/admin/orders?status=all&search=Customer Test&page=1&page_size=10", context["admin_token"])).json()
    assert search_result["items"][0]["customer_name"] == "Customer Test"

    date_filtered = (await request(
        context,
        "GET",
        f"/admin/orders?status=all&start_date={'2020-01-01T00:00:00Z'}&end_date={'2100-01-01T00:00:00Z'}",
        context["admin_token"],
    )).json()
    assert len(date_filtered) >= 1

    updated = await request(
        context,
        "PATCH",
        f"/admin/orders/{context['ids']['order']}/status",
        context["admin_token"],
        json={"status": "preparing"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "preparing"

    invalid_transition = await request(
        context,
        "PATCH",
        f"/admin/orders/{context['ids']['order']}/status",
        context["admin_token"],
        json={"status": "delivered"},
    )
    assert invalid_transition.status_code in {400, 409}
