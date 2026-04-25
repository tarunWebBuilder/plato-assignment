import json

from rest_framework import serializers
from rest_framework.renderers import JSONRenderer

from .models import BankAccount, LedgerEntry, Payout
from .selectors import balance_for_merchant


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ["id", "account_holder_name", "bank_name", "masked_account_number", "ifsc"]


class PayoutSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "amount_paise",
            "status",
            "attempts",
            "failure_reason",
            "bank_account",
            "created_at",
            "updated_at",
            "completed_at",
            "failed_at",
        ]


class LedgerEntrySerializer(serializers.ModelSerializer):
    payout_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "entry_type",
            "available_delta_paise",
            "held_delta_paise",
            "description",
            "payout_id",
            "created_at",
        ]


class PayoutCreateSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField(min_value=1)


class DashboardSerializer(serializers.Serializer):
    merchant = serializers.DictField()
    balances = serializers.DictField()
    bank_accounts = BankAccountSerializer(many=True)
    recent_ledger = LedgerEntrySerializer(many=True)
    payouts = PayoutSerializer(many=True)


def payout_response_body(payout):
    return json.loads(JSONRenderer().render(PayoutSerializer(payout).data))


def dashboard_response_body(merchant, bank_accounts, recent_ledger, payouts):
    balances = balance_for_merchant(merchant.id)
    return {
        "merchant": {"id": merchant.id, "name": merchant.name, "email": merchant.email},
        "balances": {
            "available_paise": balances["available_paise"],
            "held_paise": balances["held_paise"],
            "total_paise": balances["available_paise"] + balances["held_paise"],
        },
        "bank_accounts": BankAccountSerializer(bank_accounts, many=True).data,
        "recent_ledger": LedgerEntrySerializer(recent_ledger, many=True).data,
        "payouts": PayoutSerializer(payouts, many=True).data,
    }
