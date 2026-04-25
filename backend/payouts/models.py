import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Merchant(models.Model):
    name = models.CharField(max_length=160)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BankAccount(models.Model):
    merchant = models.ForeignKey(Merchant, related_name="bank_accounts", on_delete=models.CASCADE)
    account_holder_name = models.CharField(max_length=160)
    bank_name = models.CharField(max_length=120)
    masked_account_number = models.CharField(max_length=32)
    ifsc = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bank_name} {self.masked_account_number}"


class LedgerEntry(models.Model):
    CREDIT = "credit"
    PAYOUT_HOLD = "payout_hold"
    PAYOUT_RELEASE = "payout_release"
    PAYOUT_FINAL = "payout_final"
    ENTRY_TYPES = (
        (CREDIT, "Credit"),
        (PAYOUT_HOLD, "Payout hold"),
        (PAYOUT_RELEASE, "Payout release"),
        (PAYOUT_FINAL, "Payout final"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, related_name="ledger_entries", on_delete=models.PROTECT)
    payout = models.ForeignKey("Payout", related_name="ledger_entries", null=True, blank=True, on_delete=models.PROTECT)
    entry_type = models.CharField(max_length=32, choices=ENTRY_TYPES)
    available_delta_paise = models.BigIntegerField()
    held_delta_paise = models.BigIntegerField(default=0)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
            models.Index(fields=["payout", "entry_type"]),
        ]

    def clean(self):
        if self.available_delta_paise == 0 and self.held_delta_paise == 0:
            raise ValidationError("Ledger entry must change available or held balance.")


class Payout(models.Model):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STATUSES = (
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    )
    TERMINAL_STATUSES = {COMPLETED, FAILED}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, related_name="payouts", on_delete=models.PROTECT)
    bank_account = models.ForeignKey(BankAccount, related_name="payouts", on_delete=models.PROTECT)
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=32, choices=STATUSES, default=PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["merchant", "-created_at"]),
        ]

    def clean(self):
        if self.amount_paise <= 0:
            raise ValidationError("Payout amount must be positive.")

    @staticmethod
    def legal_transition(current_status, next_status):
        legal = {
            Payout.PENDING: {Payout.PROCESSING},
            Payout.PROCESSING: {Payout.COMPLETED, Payout.FAILED},
            Payout.COMPLETED: set(),
            Payout.FAILED: set(),
        }
        return next_status in legal[current_status]

    @staticmethod
    def retry_delay(attempts):
        return timedelta(seconds=2**attempts * 10)


class IdempotencyKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, related_name="idempotency_keys", on_delete=models.CASCADE)
    key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    payout = models.ForeignKey(Payout, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "key"], name="unique_idempotency_key_per_merchant")
        ]

    @classmethod
    def expires_tomorrow(cls):
        return timezone.now() + timedelta(hours=24)
