from django.db import models
from django.db.models import Q
from django.utils.translation import get_language


class Named(models.Model):
    name_ar = models.CharField(max_length=100, unique=True)
    name_fr = models.CharField(max_length=100, unique=True)
    disabled = models.BooleanField(default=False)

    class Meta:
        abstract = True
        ordering = ["name_ar"]

    @property
    def name(self):
        return self.name_fr if (get_language() or "ar").startswith("fr") else self.name_ar

    def __str__(self):
        return self.name


class Category(Named):
    pass


class Origin(Named):
    pass


class Purity(models.Model):
    label = models.CharField(max_length=30, unique=True)
    fineness = models.DecimalField(max_digits=5, decimal_places=1)
    disabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fineness"]
        constraints = [
            models.CheckConstraint(condition=Q(fineness__gt=0, fineness__lte=1000), name="purity_fineness_range"),
        ]

    def __str__(self):
        return self.label


class StockItem(models.Model):
    RAW = "raw"
    READY = "ready"
    SCRAP = "scrap"
    KINDS = [(RAW, "Raw"), (READY, "Ready"), (SCRAP, "Scrap")]

    kind = models.CharField(max_length=10, choices=KINDS)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="items")
    origin = models.ForeignKey(Origin, on_delete=models.PROTECT, related_name="items")
    purity = models.ForeignKey(Purity, on_delete=models.PROTECT, related_name="items")
    low_threshold_grams = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "category", "origin", "purity"],
                                    nulls_distinct=False, name="stock_item_unique_combination"),
            models.CheckConstraint(condition=~Q(kind="ready") | Q(category__isnull=False),
                                   name="stock_item_ready_needs_category"),
        ]

    def __str__(self):
        parts = [self.category.name] if self.category_id else []
        parts += [self.origin.name, self.purity.label]
        return " · ".join(parts)
