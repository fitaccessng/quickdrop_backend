from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session
from app.models.vendor import Vendor
from app.schemas.vendor import VendorDetail, VendorSummary

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorSummary])
async def list_vendors(
    search: Optional[str] = None,
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[VendorSummary]:
    query = select(Vendor).where(Vendor.is_active.is_(True))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(Vendor.name.ilike(pattern), Vendor.description.ilike(pattern)))
    if category and category.lower() != "all":
        query = query.where(Vendor.category.ilike(category))

    result = await session.execute(query.order_by(Vendor.rating.desc(), Vendor.review_count.desc()))
    return list(result.scalars().all())


@router.get("/{vendor_id}", response_model=VendorDetail)
async def get_vendor(vendor_id: int, session: AsyncSession = Depends(get_db_session)) -> VendorDetail:
    vendor = await session.scalar(
        select(Vendor)
        .where(Vendor.id == vendor_id, Vendor.is_active.is_(True))
        .options(selectinload(Vendor.products), selectinload(Vendor.reviews))
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor
