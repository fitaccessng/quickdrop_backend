from re import sub

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db_session
from app.api.deps import get_current_user, get_db
from app.models.delivery_setting import DeliverySetting
from app.models.service_category import ServiceCategory
from app.models.user import User
from app.schemas.ride import RideRequestSchema, RideResponse
from app.schemas.admin import (
    DeliveryPricingSettingsResponse,
    DeliveryPricingSettingsUpdateRequest,
    ServiceCategoryCreateRequest,
    ServiceCategoryResponse,
    ServiceCategoryUpdateRequest,
)
from app.services.rides import create_ride_request

router = APIRouter(tags=["system"])


def _slugify(value: str) -> str:
    return sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "category"


async def _get_or_create_delivery_settings(session: AsyncSession) -> DeliverySetting:
    settings = await session.scalar(select(DeliverySetting).order_by(DeliverySetting.id.asc()))
    if settings:
        return settings
    settings = DeliverySetting(base_fee=0, fee_per_km=0, free_distance_km=0)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


@router.get("/service-categories", response_model=list[ServiceCategoryResponse])
async def list_service_categories(
    session: AsyncSession = Depends(get_db_session),
) -> list[ServiceCategoryResponse]:
    result = await session.execute(
        select(ServiceCategory).where(ServiceCategory.is_active.is_(True)).order_by(ServiceCategory.name.asc())
    )
    return list(result.scalars().all())


@router.get("/delivery-settings", response_model=DeliveryPricingSettingsResponse)
async def get_delivery_settings(
    session: AsyncSession = Depends(get_db_session),
) -> DeliveryPricingSettingsResponse:
    return await _get_or_create_delivery_settings(session)


@router.post("/request-rider", response_model=RideResponse)
async def request_rider(
    payload: RideRequestSchema,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RideResponse:
    ride = await create_ride_request(current_user.id, payload, session)
    return RideResponse(
        ride_id=ride.id,
        status=ride.status,
        vehicle_type=ride.vehicle_type,
        price=ride.price,
        estimated_arrival=ride.estimated_arrival,
        driver_name=ride.driver_name,
        driver_rating=ride.driver_rating,
    )


@router.get("/admin/service-categories", response_model=list[ServiceCategoryResponse])
async def list_admin_service_categories(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> list[ServiceCategoryResponse]:
    result = await session.execute(select(ServiceCategory).order_by(ServiceCategory.name.asc()))
    return list(result.scalars().all())


@router.post("/admin/service-categories", response_model=ServiceCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_service_category(
    payload: ServiceCategoryCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> ServiceCategoryResponse:
    name = payload.name.strip()
    slug = _slugify(name)
    existing = await session.scalar(select(ServiceCategory).where(ServiceCategory.slug == slug))
    if existing:
        raise HTTPException(status_code=409, detail="Service category already exists")
    category = ServiceCategory(name=name, slug=slug, description=payload.description, is_active=payload.is_active)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


@router.patch("/admin/service-categories/{category_id}", response_model=ServiceCategoryResponse)
async def update_service_category(
    category_id: int,
    payload: ServiceCategoryUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> ServiceCategoryResponse:
    category = await session.get(ServiceCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Service category not found")

    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"]:
        category.name = values["name"].strip()
        category.slug = _slugify(category.name)
        del values["name"]
    for field, value in values.items():
        setattr(category, field, value)
    await session.commit()
    await session.refresh(category)
    return category


@router.get("/admin/delivery-settings", response_model=DeliveryPricingSettingsResponse)
async def get_admin_delivery_settings(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> DeliveryPricingSettingsResponse:
    return await _get_or_create_delivery_settings(session)


@router.put("/admin/delivery-settings", response_model=DeliveryPricingSettingsResponse)
async def update_admin_delivery_settings(
    payload: DeliveryPricingSettingsUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin),
) -> DeliveryPricingSettingsResponse:
    settings = await _get_or_create_delivery_settings(session)
    settings.base_fee = payload.base_fee
    settings.fee_per_km = payload.fee_per_km
    settings.free_distance_km = payload.free_distance_km
    await session.commit()
    await session.refresh(settings)
    return settings
