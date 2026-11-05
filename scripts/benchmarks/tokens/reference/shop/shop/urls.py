from django.urls import path
from shop import views

urlpatterns = [
    path("cart/", views.CartView.as_view()),
    path("cart/items/", views.CartItemsView.as_view()),
    path("cart/items/<uuid:pk>/", views.CartItemView.as_view()),
    path("cart/checkout/", views.CheckoutView.as_view()),
    path("payments/<uuid:pk>/confirm/", views.ConfirmPaymentView.as_view()),
]
