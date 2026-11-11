from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("lang/", views.set_language, name="set_language"),
    path("clock/confirm/", views.clock_confirm, name="clock_confirm"),
]
