from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Cart, CartItem
from .serializers import CartSerializer, CartItemSerializer
import requests

ORDER_SERVICE_URL = "http://order-service:8000"


class CartListCreate(APIView):
    def get(self, request):
        carts = Cart.objects.all()
        serializer = CartSerializer(carts, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CartSerializer(data=request.data)
        if serializer.is_valid():
            cart = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CartDetail(APIView):
    def _get_cart(self, pk):
        """Support lookup by cart id or customer id for gateway compatibility."""
        cart = Cart.objects.filter(pk=pk).first()
        if cart:
            return cart
        return Cart.objects.filter(customer_id=pk).first()

    def get(self, request, pk):
        cart = self._get_cart(pk)
        if not cart:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    def post(self, request, pk):
        # Add item to cart. Create cart automatically if it doesn't exist.
        cart = self._get_cart(pk)
        if not cart:
            cart = Cart.objects.create(customer_id=pk)

        book_id = request.data.get('book_id')
        quantity = int(request.data.get('quantity', 1))
        if not book_id:
            return Response({'book_id': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        existing_item = CartItem.objects.filter(cart=cart, book_id=book_id).first()
        if existing_item:
            existing_item.quantity += max(quantity, 1)
            existing_item.save(update_fields=['quantity'])
            return Response(CartItemSerializer(existing_item).data, status=status.HTTP_200_OK)

        serializer = CartItemSerializer(data={'book_id': book_id, 'quantity': max(quantity, 1)})
        if serializer.is_valid():
            serializer.save(cart=cart)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        cart = self._get_cart(pk)
        if not cart:
            return Response(status=status.HTTP_404_NOT_FOUND)
        cart.items.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartCheckout(APIView):
    def post(self, request, cart_pk):
        try:
            cart = Cart.objects.get(pk=cart_pk)
        except Cart.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        items = []
        for item in cart.items.all():
            items.append({"sku": str(item.book_id), "quantity": item.quantity})

        order_data = {
            "customer_id": cart.customer_id,
            "items": items,
            "payment_method": request.data.get("payment_method", "credit_card"),
            "shipping_address": request.data.get("shipping_address", "Not provided")
        }
        try:
            r = requests.post(f"{ORDER_SERVICE_URL}/api/orders/", json=order_data, timeout=10)
            r.raise_for_status()
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        cart.items.all().delete()
        return Response(r.json(), status=status.HTTP_201_CREATED)


class CartItemUpdate(APIView):
    def put(self, request, cart_pk, item_pk):
        try:
            item = CartItem.objects.get(pk=item_pk, cart_id=cart_pk)
        except CartItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = CartItemSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, cart_pk, item_pk):
        try:
            item = CartItem.objects.get(pk=item_pk, cart_id=cart_pk)
        except CartItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
