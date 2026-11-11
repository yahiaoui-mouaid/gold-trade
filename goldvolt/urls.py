from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("system.urls")),
    path("parties/", include("parties.urls")),
    path("catalog/", include("catalog.urls")),
    path("operations/", include("ledger.urls")),
    path("stock/", include("inventory.urls")),
    path("", include("reports.urls")),
    path("activity/", include("audit.urls")),
]

handler403 = "system.views.forbidden"
handler404 = "system.views.not_found"
handler500 = "system.views.server_error"
