from django.core.management.base import BaseCommand
from django.db import transaction

from payouts.models import BankAccount, LedgerEntry, Merchant


class Command(BaseCommand):
    help = "Seed demo merchants, bank accounts, and credit ledger entries."

    @transaction.atomic
    def handle(self, *args, **options):
        merchants = [
            ("Acme Studio", "ops@acme.example", 125000, 87500),
            ("Northstar Freelance", "billing@northstar.example", 60000, 40000),
            ("PixelWorks Agency", "finance@pixelworks.example", 250000, 125000),
        ]

        for index, (name, email, first_credit, second_credit) in enumerate(merchants, start=1):
            merchant, _ = Merchant.objects.get_or_create(
                email=email,
                defaults={"name": name},
            )
            BankAccount.objects.get_or_create(
                merchant=merchant,
                masked_account_number=f"XXXXXX{1000 + index}",
                defaults={
                    "account_holder_name": name,
                    "bank_name": "HDFC Bank",
                    "ifsc": f"HDFC000{index:04d}",
                },
            )

            if not LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.CREDIT).exists():
                LedgerEntry.objects.create(
                    merchant=merchant,
                    entry_type=LedgerEntry.CREDIT,
                    available_delta_paise=first_credit,
                    held_delta_paise=0,
                    description="Seeded customer payment credit",
                )
                LedgerEntry.objects.create(
                    merchant=merchant,
                    entry_type=LedgerEntry.CREDIT,
                    available_delta_paise=second_credit,
                    held_delta_paise=0,
                    description="Seeded customer payment credit",
                )

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
