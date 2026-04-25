from uuid import UUID

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Merchant, Payout
from .selectors import recent_ledger_for_merchant
from .serializers import PayoutCreateSerializer, PayoutSerializer, dashboard_response_body
from .services import PayoutError, create_payout


def merchant_from_request(request):
    merchant_id = request.headers.get("X-Merchant-Id")
    if not merchant_id:
        raise PayoutError("X-Merchant-Id header is required.", status.HTTP_401_UNAUTHORIZED)
    return get_object_or_404(Merchant, id=merchant_id)


class DashboardView(APIView):
    def get(self, request):
        merchant = merchant_from_request(request)
        bank_accounts = merchant.bank_accounts.order_by("id")
        recent_ledger = recent_ledger_for_merchant(merchant.id)
        payouts = (
            Payout.objects.filter(merchant=merchant)
            .select_related("bank_account")
            .order_by("-created_at")[:25]
        )
        return Response(dashboard_response_body(merchant, bank_accounts, recent_ledger, payouts))


class PayoutListCreateView(APIView):
    def get(self, request):
        merchant = merchant_from_request(request)
        payouts = (
            Payout.objects.filter(merchant=merchant)
            .select_related("bank_account")
            .order_by("-created_at")
        )
        return Response(PayoutSerializer(payouts, many=True).data)

    def post(self, request):
        merchant = merchant_from_request(request)
        raw_key = request.headers.get("Idempotency-Key")
        if not raw_key:
            return Response(
                {"detail": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            idempotency_key = UUID(raw_key)
        except ValueError:
            return Response(
                {"detail": "Idempotency-Key must be a UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PayoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            response_status, body = create_payout(
                merchant_id=merchant.id,
                amount_paise=serializer.validated_data["amount_paise"],
                bank_account_id=serializer.validated_data["bank_account_id"],
                idempotency_key=idempotency_key,
                payload=serializer.validated_data,
            )
        except PayoutError as exc:
            return Response({"detail": str(exc)}, status=exc.status_code)

        return Response(body, status=response_status)


class PayoutDetailView(APIView):
    def get(self, request, payout_id):
        merchant = merchant_from_request(request)
        payout = get_object_or_404(
            Payout.objects.select_related("bank_account"),
            id=payout_id,
            merchant=merchant,
        )
        return Response(PayoutSerializer(payout).data)
