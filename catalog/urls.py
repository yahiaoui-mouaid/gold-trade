from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="catalog"),
    path("<str:kind>/<int:pk>/toggle/", views.toggle, name="catalog_toggle"),
    path("category/<int:pk>/delete/", views.delete_category, name="category_delete"),
]
