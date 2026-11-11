from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup, name="setup"),
    path("login/", views.login_view, name="login"),
    path("login/code/", views.login_code, name="login_code"),
    path("login/forgot/", views.forgot_password, name="forgot"),
    path("logout/", views.logout_view, name="logout"),
    path("account/enroll/", views.enroll, name="enroll"),
    path("account/recovery/", views.recovery, name="recovery"),
    path("account/password/", views.change_password, name="change_password"),
    path("confirm/", views.confirm, name="confirm"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/reset/", views.user_reset, name="user_reset"),
    path("users/<int:pk>/toggle/", views.user_toggle, name="user_toggle"),
]
