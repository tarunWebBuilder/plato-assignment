import hashlib
import json
import random

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from .models import BankAccount, IdempotencyKey, LedgerEntry, Merchant, Payout
from .selectors import balance_for_merchant
from .serializers import payout_response_body


class PayoutError(Exception):
    def __init__(self, message, status_code=status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.status_code = status_code


def canonical_request_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_payout(*, merchant_id, amount_paise, bank_account_id, idempotency_key, payload):
    request_hash = canonical_request_hash(payload)
    now = timezone.now()

    with transaction.atomic():
        IdempotencyKey.objects.filter(expires_at__lt=now).delete()

        existing_key = (
            IdempotencyKey.objects.select_for_update()
            .filter(merchant_id=merchant_id, key=idempotency_key)
            .first()
        )
        if existing_key:
            if existing_key.request_hash != request_hash:
                raise PayoutError(
                    "Idempotency-Key was already used with a different request body.",
                    status.HTTP_409_CONFLICT,
                )
            if existing_key.response_body is not None:
                return existing_key.response_status, existing_key.response_body

        try:
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)
            bank_account = BankAccount.objects.select_for_update().get(
                id=bank_account_id,
                merchant=merchant,
            )
        except ObjectDoesNotExist:
            raise PayoutError("Merchant or bank account not found.", status.HTTP_404_NOT_FOUND)
        balances = balance_for_merchant(merchant.id)
        if balances["available_paise"] < amount_paise:
            raise PayoutError("Insufficient available balance.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        if existing_key is None:
            try:
                with transaction.atomic():
                    existing_key = IdempotencyKey.objects.create(
                        merchant=merchant,
                        key=idempotency_key,
                        request_hash=request_hash,
                        expires_at=IdempotencyKey.expires_tomorrow(),
                    )
            except IntegrityError:
                existing_key = IdempotencyKey.objects.select_for_update().get(
                    merchant=merchant,
                    key=idempotency_key,
                )
                if existing_key.request_hash != request_hash:
                    raise PayoutError(
                        "Idempotency-Key was already used with a different request body.",
                        status.HTTP_409_CONFLICT,
                    )
                return existing_key.response_status, existing_key.response_body

        payout = Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=amount_paise,
            status=Payout.PENDING,
        )
        LedgerEntry.objects.create(
            merchant=merchant,
            payout=payout,
            entry_type=LedgerEntry.PAYOUT_HOLD,
            available_delta_paise=-amount_paise,
            held_delta_paise=amount_paise,
            description=f"Payout hold for {payout.id}",
        )

        body = payout_response_body(
            Payout.objects.select_related("bank_account").get(id=payout.id)
        )
        existing_key.payout = payout
        existing_key.response_status = status.HTTP_201_CREATED
        existing_key.response_body = body
        existing_key.expires_at = IdempotencyKey.expires_tomorrow()
        existing_key.save(
            update_fields=["payout", "response_status", "response_body", "expires_at"]
        )

        def enqueue_processing():
            from .tasks import process_pending_payouts

            process_pending_payouts.delay()

        transaction.on_commit(enqueue_processing)
        return status.HTTP_201_CREATED, body


def transition_payout(payout, next_status, *, failure_reason=""):
    if not Payout.legal_transition(payout.status, next_status):
        raise PayoutError(f"Illegal payout transition {payout.status} -> {next_status}.")

    now = timezone.now()
    update_fields = ["status", "updated_at"]
    payout.status = next_status

    if next_status == Payout.COMPLETED:
        payout.completed_at = now
        update_fields.append("completed_at")
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            payout=payout,
            entry_type=LedgerEntry.PAYOUT_FINAL,
            available_delta_paise=0,
            held_delta_paise=-payout.amount_paise,
            description=f"Payout completed for {payout.id}",
        )
    elif next_status == Payout.FAILED:
        payout.failed_at = now
        payout.failure_reason = failure_reason
        update_fields.extend(["failed_at", "failure_reason"])
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            payout=payout,
            entry_type=LedgerEntry.PAYOUT_RELEASE,
            available_delta_paise=payout.amount_paise,
            held_delta_paise=-payout.amount_paise,
            description=f"Payout failed and funds released for {payout.id}",
        )

    payout.save(update_fields=update_fields)
    return payout


def mark_processing(payout):
    if not Payout.legal_transition(payout.status, Payout.PROCESSING):
        raise PayoutError(f"Illegal payout transition {payout.status} -> processing.")

    now = timezone.now()
    payout.status = Payout.PROCESSING
    payout.attempts += 1
    payout.processing_started_at = now
    payout.next_retry_at = now + Payout.retry_delay(payout.attempts)
    payout.save(
        update_fields=[
            "status",
            "attempts",
            "processing_started_at",
            "next_retry_at",
            "updated_at",
        ]
    )
    return payout


def settle_processing_payout(payout):
    outcome = random.random()
    if outcome < 0.70:
        return transition_payout(payout, Payout.COMPLETED)
    if outcome < 0.90:
        return transition_payout(payout, Payout.FAILED, failure_reason="Bank settlement failed.")
    return payout


def fail_after_max_attempts(payout):
    return transition_payout(
        payout,
        Payout.FAILED,
        failure_reason="Payout failed after maximum retry attempts.",
    )
