from datetime import timedelta

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from .models import Merchant, Payout
from .services import fail_after_max_attempts, mark_processing, settle_processing_payout


def lockable_queryset(queryset):
    if connection.features.has_select_for_update_skip_locked:
        return queryset.select_for_update(skip_locked=True)
    return queryset.select_for_update()


@shared_task
def process_pending_payouts(limit=20):
    payout_ids = list(
        Payout.objects.filter(status=Payout.PENDING)
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )

    processed = 0
    for payout_id in payout_ids:
        with transaction.atomic():
            payout = (
                lockable_queryset(Payout.objects.select_related("merchant", "bank_account"))
                .filter(id=payout_id, status=Payout.PENDING)
                .first()
            )
            if payout is None:
                continue
            Merchant.objects.select_for_update().get(id=payout.merchant_id)
            mark_processing(payout)
            settle_processing_payout(payout)
            processed += 1
    return processed


@shared_task
def retry_stuck_processing_payouts(limit=20):
    now = timezone.now()
    stuck_before = now - timedelta(seconds=30)
    payout_ids = list(
        Payout.objects.filter(
            status=Payout.PROCESSING,
            processing_started_at__lte=stuck_before,
            next_retry_at__lte=now,
        )
        .order_by("next_retry_at", "created_at")
        .values_list("id", flat=True)[:limit]
    )

    processed = 0
    for payout_id in payout_ids:
        with transaction.atomic():
            payout = (
                lockable_queryset(Payout.objects.select_related("merchant", "bank_account"))
                .filter(id=payout_id, status=Payout.PROCESSING)
                .first()
            )
            if payout is None:
                continue
            Merchant.objects.select_for_update().get(id=payout.merchant_id)
            if payout.attempts >= 3:
                fail_after_max_attempts(payout)
            else:
                payout.attempts += 1
                payout.processing_started_at = timezone.now()
                payout.next_retry_at = timezone.now() + Payout.retry_delay(payout.attempts)
                payout.save(
                    update_fields=[
                        "attempts",
                        "processing_started_at",
                        "next_retry_at",
                        "updated_at",
                    ]
                )
                settle_processing_payout(payout)
            processed += 1
    return processed
