from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from .models import LedgerEntry


def balance_for_merchant(merchant_id):
    return LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        available_paise=Coalesce(Sum("available_delta_paise"), Value(0)),
        held_paise=Coalesce(Sum("held_delta_paise"), Value(0)),
    )


def recent_ledger_for_merchant(merchant_id, limit=25):
    return (
        LedgerEntry.objects.filter(merchant_id=merchant_id)
        .select_related("payout")
        .order_by("-created_at")[:limit]
    )
