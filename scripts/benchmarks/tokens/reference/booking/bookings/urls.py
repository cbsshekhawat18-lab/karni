from bookings import views
from django.urls import path

urlpatterns = [path("payments/<uuid:pk>/confirm/", views.ConfirmPaymentView.as_view())]
