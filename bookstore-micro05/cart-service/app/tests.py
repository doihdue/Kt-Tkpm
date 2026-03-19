from django.test import TestCase
from .models import Cart, CartItem
from django.urls import reverse
from rest_framework.test import APIClient

class CartAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_cart(self):
        response = self.client.post('/api/carts/', {'customer_id': 1}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Cart.objects.count(), 1)

    def test_add_item(self):
        cart = Cart.objects.create(customer_id=2)
        response = self.client.post(f'/api/carts/{cart.id}/', {'book_id': 10, 'quantity': 2}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(cart.items.count(), 1)

    def test_update_item(self):
        cart = Cart.objects.create(customer_id=3)
        item = CartItem.objects.create(cart=cart, book_id=5, quantity=1)
        response = self.client.put(f'/api/carts/{cart.id}/items/{item.id}/', {'quantity': 4}, format='json')
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
