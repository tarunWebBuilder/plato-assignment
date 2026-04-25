from datetime import timedelta
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import BankAccount, LedgerEntry, Merchant, Payout
from .selectors import balance_for_merchant
from .services import PayoutError, create_payout, transition_payout
from .tasks import retry_stuck_processing_payouts


class PayoutEngineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.merchant = Merchant.objects.create(name="Test Merchant", email="merchant@example.com")
        self.bank = BankAccount.objects.create(
            merchant=self.merchant,
            account_holder_name="Test Merchant",
            bank_name="HDFC Bank",
            masked_account_number="XXXX1234",
            ifsc="HDFC0000001",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.CREDIT,
            available_delta_paise=10000,
            held_delta_paise=0,
            description="Credit",
        )

    def auth_headers(self, key=None):
        headers = {"HTTP_X_MERCHANT_ID": str(self.merchant.id)}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = str(key)
        return headers

    def test_payout_holds_funds_and_preserves_balance_invariant(self):
        response = self.client.post(
            reverse("payouts"),
            {"amount_paise": 6000, "bank_account_id": self.bank.id},
            format="json",
            **self.auth_headers(uuid4()),
        )

        self.assertEqual(response.status_code, 201)
        balances = balance_for_merchant(self.merchant.id)
        self.assertEqual(balances["available_paise"], 4000)
        self.assertEqual(balances["held_paise"], 6000)
        self.assertEqual(balances["available_paise"] + balances["held_paise"], 10000)

    def test_idempotency_replays_same_response_without_duplicate_payout(self):
        key = uuid4()
        payload = {"amount_paise": 6000, "bank_account_id": self.bank.id}

        first = self.client.post(reverse("payouts"), payload, format="json", **self.auth_headers(key))
        second = self.client.post(reverse("payouts"), payload, format="json", **self.auth_headers(key))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Payout.objects.count(), 1)

    def test_same_idempotency_key_with_different_body_is_rejected(self):
        key = uuid4()
        self.client.post(
            reverse("payouts"),
            {"amount_paise": 6000, "bank_account_id": self.bank.id},
            format="json",
            **self.auth_headers(key),
        )
        response = self.client.post(
            reverse("payouts"),
            {"amount_paise": 5000, "bank_account_id": self.bank.id},
            format="json",
            **self.auth_headers(key),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Payout.objects.count(), 1)

    def test_insufficient_funds_rejected_cleanly(self):
        create_payout(
            merchant_id=self.merchant.id,
            amount_paise=6000,
            bank_account_id=self.bank.id,
            idempotency_key=uuid4(),
            payload={"amount_paise": 6000, "bank_account_id": self.bank.id},
        )

        response = self.client.post(
            reverse("payouts"),
            {"amount_paise": 6000, "bank_account_id": self.bank.id},
            format="json",
            **self.auth_headers(uuid4()),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Payout.objects.count(), 1)

    def test_illegal_state_transition_is_rejected(self):
        _, body = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=1000,
            bank_account_id=self.bank.id,
            idempotency_key=uuid4(),
            payload={"amount_paise": 1000, "bank_account_id": self.bank.id},
        )
        payout = Payout.objects.get(id=body["id"])
        payout.status = Payout.COMPLETED

        with self.assertRaises(PayoutError):
            transition_payout(payout, Payout.PENDING)

    def test_failed_payout_releases_funds_atomically(self):
        _, body = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=6000,
            bank_account_id=self.bank.id,
            idempotency_key=uuid4(),
            payload={"amount_paise": 6000, "bank_account_id": self.bank.id},
        )
        payout = Payout.objects.get(id=body["id"])
        payout.status = Payout.PROCESSING
        transition_payout(payout, Payout.FAILED, failure_reason="Bank failed")

        balances = balance_for_merchant(self.merchant.id)
        self.assertEqual(balances["available_paise"], 10000)
        self.assertEqual(balances["held_paise"], 0)

    def test_stuck_processing_fails_after_three_attempts_and_releases(self):
        _, body = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=6000,
            bank_account_id=self.bank.id,
            idempotency_key=uuid4(),
            payload={"amount_paise": 6000, "bank_account_id": self.bank.id},
        )
        payout = Payout.objects.get(id=body["id"])
        payout.status = Payout.PROCESSING
        payout.attempts = 3
        payout.processing_started_at = timezone.now() - timedelta(seconds=40)
        payout.next_retry_at = timezone.now() - timedelta(seconds=1)
        payout.save()

        retry_stuck_processing_payouts()

        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.FAILED)
        balances = balance_for_merchant(self.merchant.id)
        self.assertEqual(balances["available_paise"], 10000)
        self.assertEqual(balances["held_paise"], 0)
