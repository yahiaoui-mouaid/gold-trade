from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import requires

from . import services
from .models import Category, Origin, Purity
from .services import CatalogError

MODELS = {"category": Category, "origin": Origin, "purity": Purity}


@requires("catalog.manage")
def index(request):
    error = None
    if request.method == "POST":
        kind = request.POST.get("type")
        try:
            if kind == "purity":
                services.create_purity(request.user, request.POST.get("label", ""), request.POST.get("fineness", ""))
            elif kind in ("category", "origin"):
                services.create_named(request.user, MODELS[kind], request.POST.get("name_ar", ""),
                                      request.POST.get("name_fr", ""))
        except CatalogError as exc:
            error = str(exc)
        else:
            return redirect("catalog")
    return render(request, "catalog/index.html", {
        "categories": Category.objects.all(), "origins": Origin.objects.all(),
        "purities": Purity.objects.all(), "error": error,
    })


@requires("catalog.manage")
def toggle(request, kind, pk):
    if kind not in MODELS:
        raise Http404
    row = get_object_or_404(MODELS[kind], pk=pk)
    if request.method == "POST":
        services.set_disabled(request.user, row, not row.disabled)
    return redirect("catalog")


@requires("catalog.manage")
def delete_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    error = None
    if request.method == "POST":
        try:
            services.delete_category(request.user, category)
        except CatalogError as exc:
            error = str(exc)
        else:
            return redirect("catalog")
    return render(request, "catalog/index.html", {
        "categories": Category.objects.all(), "origins": Origin.objects.all(),
        "purities": Purity.objects.all(), "error": error,
    })
