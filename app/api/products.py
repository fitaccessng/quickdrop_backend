from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_vendor, get_db_session
from app.models.product import Product
from app.models.vendor import Vendor
from app.schemas.product import ProductCreateRequest, ProductSummary, ProductUpdateRequest

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductSummary])
async def list_products(
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    include_unavailable: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductSummary]:
    query = select(Product)
    if not include_unavailable:
        query = query.where(Product.is_available.is_(True))
    if vendor_id:
        query = query.where(Product.vendor_id == vendor_id)
    if category and category.lower() != "all":
        query = query.where(Product.category.ilike(category))

    result = await session.execute(query.order_by(Product.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> ProductSummary:
    # Check if vendor is approved
    if not current_vendor.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your vendor account is pending approval. You cannot upload products until your account is approved by the admin."
        )
    
    values = payload.model_dump()
    if values.get("image_urls"):
        values["image_url"] = values["image_urls"][0]
    if values["stock_quantity"] <= 0:
        values["is_available"] = False
    product = Product(vendor_id=current_vendor.id, **values)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductSummary)
async def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_vendor: Vendor = Depends(get_current_vendor),
) -> ProductSummary:
    product = await session.scalar(select(Product).where(Product.id == product_id, Product.vendor_id == current_vendor.id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    if payload.image_urls is not None:
        product.image_url = payload.image_urls[0] if payload.image_urls else None

    if payload.stock_quantity is not None and product.stock_quantity <= 0:
        product.is_available = False

    await session.commit()
    await session.refresh(product)
    return product
