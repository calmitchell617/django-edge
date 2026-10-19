from django.urls import path

from edge import views

urlpatterns = [
    path("", views.health),
    path("api/health/", views.health),
    path("api/login/", views.sign_in),
    path("api/logout/", views.sign_out),
    path("api/me/", views.whoami),
    path("api/posts/", views.posts),
    path("api/posts/<int:pk>/", views.post_detail),
    path("_control/<str:action>/", views.control),
]
