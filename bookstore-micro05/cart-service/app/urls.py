from django.urls import path
from .views import CartListCreate, CartDetail, CartItemUpdate, CartCheckout

urlpatterns = [
    path('', CartListCreate.as_view()),
    path('carts/', CartListCreate.as_view()),
    path('carts/<int:pk>/', CartDetail.as_view()),
    path('carts/<int:cart_pk>/checkout/', CartCheckout.as_view()),
    path('carts/<int:cart_pk>/items/<int:item_pk>/', CartItemUpdate.as_view()),
]
