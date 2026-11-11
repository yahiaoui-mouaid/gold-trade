from django.urls import path

from . import views

urlpatterns = [
    path("", views.party_list, name="parties"),
    path("new/", views.party_new, name="party_new"),
    path("search/", views.party_search, name="party_search"),
    path("quick-add/", views.party_quick_add, name="party_quick_add"),
    path("<int:pk>/", views.party_folder, name="party_folder"),
    path("<int:pk>/edit/", views.party_edit, name="party_edit"),
    path("<int:pk>/archive/", views.party_archive, name="party_archive"),
]
