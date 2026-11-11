"""History tables. The app's database role can only read and insert here."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from catalog.models import Origin, StockItem
from parties.models import Party

MONEY = {"max_digits": 14, "decimal_places": 2}
GROSS = {"max_digits": 12, "decimal_places": 3}
FINE = {"max_digits": 18, "decimal_places": 7}


class AppendOnly(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    import_batch_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True


class Transaction(AppendOnly):
    SALE = "sale"
    PURCHASE = "purchase"
    PAYMENT = "payment"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"
    KINDS = [(SALE, "Sale"), (PURCHASE, "Purchase"), (PAYMENT, "Payment"),
             (ADJUSTMENT, "Adjustment"), (REVERSAL, "Reversal")]

    number = models.CharField(max_length=32, unique=True)
    kind = models.CharField(max_length=12, choices=KINDS, db_index=True)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    operation_at = models.DateTimeField(db_index=True, help_text="Entered by the user; defaults to now.")
    recorded_at = models.DateTimeField(db_index=True, help_text="Real server time; never editable.")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    author_name = models.CharField(max_length=150)
    reversal_of = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="reversed_by")
    money_received = models.DecimalField(default=0, **MONEY)
    money_given = models.DecimalField(default=0, **MONEY)
    facon_total = models.DecimalField(default=0, **MONEY)
    money_difference = models.DecimalField(default=0, **MONEY)
    form_token = models.UUIDField(null=True, blank=True, unique=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-operation_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(money_received__gte=0, money_given__gte=0),
                                   name="transaction_money_not_negative"),
            models.CheckConstraint(condition=Q(party__isnull=False) | Q(kind__in=["adjustment", "reversal"]),
                                   name="transaction_party_required"),
        ]


class TransactionLine(AppendOnly):
    IN = "in"
    OUT = "out"

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="lines")
    direction = models.CharField(max_length=3, choices=[(IN, "In"), (OUT, "Out")])
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="+")
    gross_grams = models.DecimalField(**GROSS)
    fineness = models.DecimalField(max_digits=5, decimal_places=1)
    fine_grams = models.DecimalField(**FINE)
    pieces = models.IntegerField(default=0)
    facon_rate = models.DecimalField(null=True, blank=True, **MONEY)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(gross_grams__gt=0), name="line_gross_positive"),
            models.CheckConstraint(condition=Q(fine_grams__lte=models.F("gross_grams")), name="line_fine_le_gross"),
            models.CheckConstraint(condition=Q(fineness__gt=0, fineness__lte=1000), name="line_fineness_range"),
            models.CheckConstraint(condition=Q(pieces__gte=0), name="line_pieces_not_negative"),
        ]


class StockMovement(AppendOnly):
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="stock_movements")
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    grams = models.DecimalField(**GROSS)
    pieces = models.IntegerField(default=0)


class PartyLedgerEntry(AppendOnly):
    """Positive means the party owes the shop; negative, the shop owes the party."""

    MONEY_ASSET = "money"
    GOLD = "gold"

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="ledger_entries")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="ledger_entries")
    asset = models.CharField(max_length=5, choices=[(MONEY_ASSET, "Money"), (GOLD, "Gold")])
    origin = models.ForeignKey(Origin, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    amount_da = models.DecimalField(null=True, blank=True, **MONEY)
    fine_grams = models.DecimalField(null=True, blank=True, **FINE)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(asset="money", origin__isnull=True, amount_da__isnull=False, fine_grams__isnull=True)
                    | Q(asset="gold", origin__isnull=False, amount_da__isnull=True, fine_grams__isnull=False)
                ),
                name="ledger_entry_asset_shape",
            ),
        ]
        indexes = [models.Index(fields=["party", "asset", "origin"])]


class CashMovement(AppendOnly):
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="cash_movements")
    amount_da = models.DecimalField(**MONEY)


class DocumentSequence(models.Model):
    year = models.IntegerField(primary_key=True)
    last_number = models.BigIntegerField(default=0)
