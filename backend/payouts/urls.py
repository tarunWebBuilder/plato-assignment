from django.urls import path

from .views import DashboardView, PayoutDetailView, PayoutListCreateView

urlpatterns = [
    path("dashboard", DashboardView.as_view(), name="dashboard"),
    path("payouts", PayoutListCreateView.as_view(), name="payouts"),
    path("payouts/<uuid:payout_id>", PayoutDetailView.as_view(), name="payout-detail"),
]
