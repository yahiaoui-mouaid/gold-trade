from django.urls import path

from . import views

urlpatterns = [
    path("", views.operations, name="operations"),
    path("new/sale/", views.new_sale, name="new_sale"),
    path("new/purchase/", views.new_purchase, name="new_purchase"),
    path("new/payment/", views.new_payment, name="new_payment"),
    path("preview/", views.preview, name="preview"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("<int:pk>/void/", views.void, name="void"),
]
