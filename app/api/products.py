from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_current_vendor, get_db_session
from app.models.product import Product, ProductReview
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.product import (
    ProductCreateRequest,
    ProductDetailResponse,
    ProductReviewCreateRequest,
    ProductReviewResponse,
    ProductReviewUpdateRequest,
    ProductSummary,
    ProductUpdateRequest,
)

router = APIRouter(prefix="/products", tags=["products"])


async def _refresh_product_rating(session: AsyncSession, product: Product) -> None:
    rating_result = await session.execute(
        select(
            func.coalesce(func.avg(ProductReview.rating), 0),
            func.count(ProductReview.id),
        ).where(ProductReview.product_id == product.id)
    )
    average_rating, review_count = rating_result.one()
    product.rating = round(float(average_rating or 0), 2)
    product.review_count = int(review_count or 0)

    vendor_rating_result = await session.execute(
        select(
            func.coalesce(func.avg(Product.rating), 0),
            func.coalesce(func.sum(Product.review_count), 0),
        ).where(Product.vendor_id == product.vendor_id)
    )
    vendor_rating, vendor_review_count = vendor_rating_result.one()
    vendor = await session.get(Vendor, product.vendor_id)
    if vendor:
        vendor.rating = round(float(vendor_rating or 0), 2)
        vendor.review_count = int(vendor_review_count or 0)


@router.get("", response_model=list[ProductSummary])
async def list_products(
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    include_unavailable: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductSummary]:
    query = select(Product).options(selectinload(Product.reviews))
    if not include_unavailable:
        query = query.where(Product.is_available.is_(True))
    if vendor_id:
        query = query.where(Product.vendor_id == vendor_id)
    if category and category.lower() != "all":
        query = query.where(Product.category.ilike(category))

    result = await session.execute(query.order_by(Product.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(product_id: int, session: AsyncSession = Depends(get_db_session)) -> ProductDetailResponse:
    product = await session.scalar(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.reviews))
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


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


@router.post("/{product_id}/reviews", response_model=ProductReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_product_review(
    product_id: int,
    payload: ProductReviewCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ProductReviewResponse:
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can review products")

    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = await session.scalar(
        select(ProductReview).where(
            ProductReview.product_id == product_id,
            ProductReview.user_id == current_user.id,
        )
    )
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        review = existing
    else:
        review = ProductReview(
            product_id=product_id,
            user_id=current_user.id,
            author_name=current_user.full_name,
            rating=payload.rating,
            comment=payload.comment,
        )
        session.add(review)

    await session.flush()
    await _refresh_product_rating(session, product)
    await session.commit()
    await session.refresh(review)
    return review


@router.get("/{product_id}/reviews", response_model=list[ProductReviewResponse])
async def list_product_reviews(
    product_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductReviewResponse]:
    result = await session.execute(
        select(ProductReview)
        .where(ProductReview.product_id == product_id)
        .order_by(ProductReview.updated_at.desc(), ProductReview.created_at.desc())
    )
    return list(result.scalars().all())


@router.patch("/{product_id}/reviews/{review_id}", response_model=ProductReviewResponse)
async def update_product_review(
    product_id: int,
    review_id: int,
    payload: ProductReviewUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ProductReviewResponse:
    review = await session.scalar(
        select(ProductReview).where(ProductReview.id == review_id, ProductReview.product_id == product_id)
    )
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own review")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(review, field, value)

    product = await session.get(Product, product_id)
    await session.flush()
    await _refresh_product_rating(session, product)
    await session.commit()
    await session.refresh(review)
    return review
