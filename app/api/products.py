from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.product import Product
from app.schemas.product import ProductSummary

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductSummary])
async def list_products(
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductSummary]:
    query = select(Product).where(Product.is_available.is_(True))
    if vendor_id:
        query = query.where(Product.vendor_id == vendor_id)
    if category and category.lower() != "all":
        query = query.where(Product.category.ilike(category))

    result = await session.execute(query.order_by(Product.created_at.desc()))
    return list(result.scalars().all())
