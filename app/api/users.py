from fastapi import APIRouter, Depends, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db_session
from app.models.address import Address
from app.models.user import User
from app.schemas.order import OrderResponse
from app.schemas.user import AddressCreate, AddressResponse, UserProfile, UserProfileUpdate
from app.services.orders import get_orders_for_user
from app.api.orders import serialize_order

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/me", response_model=UserProfile)
async def get_profile(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> UserProfile:
    user = await session.scalar(select(User).where(User.id == current_user.id).options(selectinload(User.addresses)))
    return user


@router.patch("/me", response_model=UserProfile)
async def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserProfile:
    user = await session.scalar(select(User).where(User.id == current_user.id).options(selectinload(User.addresses)))
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    if user.city and user.state and user.street:
        user.is_onboarded = True
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: AddressCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AddressResponse:
    if payload.is_default:
        await session.execute(update(Address).where(Address.user_id == current_user.id).values(is_default=False))

    address = Address(user_id=current_user.id, **payload.model_dump())
    session.add(address)
    await session.commit()
    await session.refresh(address)
    return address


@router.get("/orders", response_model=list[OrderResponse], status_code=status.HTTP_200_OK)
async def get_user_order_history(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[OrderResponse]:
    orders = await get_orders_for_user(session, current_user.id)
    return [serialize_order(order) for order in orders]
