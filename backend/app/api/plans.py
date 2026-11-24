"""Plans catalog, payment checkout/verification, and token usage endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student
from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import PaymentTransaction, Plan, TokenUsageLog, User
from app.services.account_service import get_user_storage_quota_bytes
from app.services.auth_billing_service import (
    apply_plan_to_user,
    get_or_init_billing_settings,
    get_or_init_plans,
    get_user_today_tokens,
    serialize_plan,
    serialize_user,
    utc_iso,
)
from app.services.payment_provider import get_payment_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)


class VerifyPaymentBody(BaseModel):
    transaction_id: str | None = None
    authority: str = Field(min_length=1, max_length=128)
    status: str | None = None


@router.get("")
async def list_public_plans(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    settings = get_settings()
    billing = await get_or_init_billing_settings(session)
    plans = await get_or_init_plans(session)
    await session.commit()
    return {
        "plans": [serialize_plan(plan) for plan in plans if plan.is_active],
        "token_price_per_1k_toman": billing.token_price_per_1k_toman,
        "starter_tokens": billing.starter_tokens,
        "starter_duration_days": billing.starter_duration_days,
        "payment_mode": "demo" if (settings.demo_mode or settings.payment_provider == "demo") else settings.payment_provider,
    }


@router.post("/checkout")
async def checkout_plan(
    body: CheckoutRequest,
    request: Request,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await get_or_init_plans(session)
    plan = await session.scalar(
        select(Plan).where(Plan.code == body.plan_code.strip(), Plan.is_active.is_(True))
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="پلن انتخاب‌شده پیدا نشد یا غیرفعال است.")

    settings = get_settings()
    provider = get_payment_provider(settings)
    tx = PaymentTransaction(
        user_id=user.id,
        plan_code=plan.code,
        plan_name=plan.name,
        amount_toman=plan.price_toman,
        tokens_granted=plan.token_quota,
        duration_days=plan.duration_days,
        provider=provider.provider_name,
        status="pending",
    )
    session.add(tx)
    await session.flush()

    origin = settings.public_app_url or str(request.base_url).rstrip("/")
    callback_url = f"{origin}/?payment_tx={tx.id}"
    try:
        init_res = await provider.create_payment(
            transaction_id=tx.id,
            amount_toman=plan.price_toman,
            description=f"خرید اشتراک {plan.name} درسیار ({plan.token_quota:,} توکن)",
            callback_url=callback_url,
            mobile=user.phone_number,
        )
    except Exception as error:  # noqa: BLE001
        tx.status = "failed"
        await session.commit()
        logger.exception("Payment init failed for transaction %s", tx.id)
        raise HTTPException(
            status_code=503,
            detail="درگاه پرداخت در حال حاضر در دسترس نیست. لطفاً بعداً تلاش کنید.",
        ) from error

    tx.authority = init_res.authority
    tx.ref_id = init_res.ref_id
    now = datetime.now(timezone.utc)

    if init_res.status == "paid":
        tx.status = "paid"
        tx.paid_at = now
        apply_plan_to_user(
            user,
            plan_code=plan.code,
            plan_name=plan.name,
            tokens_granted=plan.token_quota,
            duration_days=plan.duration_days,
            carry_over_valid=True,
            now=now,
        )
        await session.commit()
        await session.refresh(user)
        billing = await get_or_init_billing_settings(session)
        today_tokens = await get_user_today_tokens(session, user.id)
        return {
            "status": "paid",
            "transaction_id": tx.id,
            "ref_id": tx.ref_id,
            "plan": serialize_plan(plan),
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
                storage_quota_bytes=int(getattr(plan, "storage_quota_bytes", 104_857_600) or 104_857_600),
                now=now,
            ),
        }

    await session.commit()
    return {
        "status": "redirect",
        "transaction_id": tx.id,
        "authority": tx.authority,
        "payment_url": init_res.payment_url,
    }


async def _verify_transaction(
    *,
    session: AsyncSession,
    user: User,
    authority: str,
    transaction_id: str | None,
    gateway_status: str | None,
) -> dict[str, object]:
    query = select(PaymentTransaction).where(
        PaymentTransaction.user_id == user.id,
        PaymentTransaction.authority == authority,
    )
    if transaction_id:
        query = query.where(PaymentTransaction.id == transaction_id)
    tx = await session.scalar(query)
    if tx is None:
        raise HTTPException(status_code=404, detail="تراکنش یافت نشد.")

    billing = await get_or_init_billing_settings(session)
    if tx.status == "paid":
        today_tokens = await get_user_today_tokens(session, user.id)
        storage_quota = await get_user_storage_quota_bytes(session, user, billing)
        return {
            "status": "paid",
            "transaction_id": tx.id,
            "ref_id": tx.ref_id,
            "user": serialize_user(
                user,
                today_tokens=today_tokens,
                token_price_per_1k_toman=billing.token_price_per_1k_toman,
                storage_quota_bytes=storage_quota,
            ),
        }

    if gateway_status and gateway_status.upper() != "OK":
        tx.status = "cancelled"
        await session.commit()
        raise HTTPException(status_code=402, detail="پرداخت توسط کاربر لغو یا ناموفق شد.")

    provider = get_payment_provider(get_settings())
    result = await provider.verify_payment(authority=authority, amount_toman=tx.amount_toman)
    if not result.paid:
        tx.status = "failed"
        await session.commit()
        raise HTTPException(status_code=402, detail=f"تأیید پرداخت انجام نشد: {result.message or ''}".strip())

    now = datetime.now(timezone.utc)
    tx.status = "paid"
    tx.ref_id = result.ref_id
    tx.paid_at = now
    apply_plan_to_user(
        user,
        plan_code=tx.plan_code,
        plan_name=tx.plan_name,
        tokens_granted=tx.tokens_granted,
        duration_days=tx.duration_days,
        carry_over_valid=True,
        now=now,
    )
    await session.commit()
    await session.refresh(user)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "status": "paid",
        "transaction_id": tx.id,
        "ref_id": tx.ref_id,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
            now=now,
        ),
    }


@router.post("/verify")
async def verify_plan_payment_post(
    body: VerifyPaymentBody,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await _verify_transaction(
        session=session,
        user=user,
        authority=body.authority,
        transaction_id=body.transaction_id,
        gateway_status=body.status,
    )


@router.get("/verify")
async def verify_plan_payment_get(
    Authority: str = Query(..., min_length=1),
    Status: str | None = Query(None),
    payment_tx: str | None = Query(None),
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await _verify_transaction(
        session=session,
        user=user,
        authority=Authority,
        transaction_id=payment_tx,
        gateway_status=Status,
    )


@router.get("/usage")
async def get_my_usage(
    response: Response,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    logs = (
        await session.scalars(
            select(TokenUsageLog)
            .where(TokenUsageLog.user_id == user.id)
            .order_by(TokenUsageLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    payments = (
        await session.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.user_id == user.id)
            .order_by(PaymentTransaction.created_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
        ),
        "token_price_per_1k_toman": billing.token_price_per_1k_toman,
        "logs": [
            {
                "id": item.id,
                "action": item.action,
                "book_id": item.book_id,
                "prompt_tokens": item.prompt_tokens,
                "completion_tokens": item.completion_tokens,
                "total_tokens": item.total_tokens,
                "cost_toman": item.cost_toman,
                "created_at": utc_iso(item.created_at),
            }
            for item in logs
        ],
        "transactions": [
            {
                "id": tx.id,
                "plan_code": tx.plan_code,
                "plan_name": tx.plan_name,
                "amount_toman": tx.amount_toman,
                "tokens_granted": tx.tokens_granted,
                "duration_days": tx.duration_days,
                "provider": tx.provider,
                "status": tx.status,
                "ref_id": tx.ref_id,
                "created_at": utc_iso(tx.created_at),
                "paid_at": utc_iso(tx.paid_at),
            }
            for tx in payments
        ],
    }
