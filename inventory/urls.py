from django.urls import path

from . import views

urlpatterns = [
    path("", views.stock, name="stock"),
    path("movements/", views.movements, name="movements"),
    path("adjust/", views.adjust, name="stock_adjust"),
]
