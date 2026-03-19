from django.test import TestCase
from rest_framework.test import APIClient
from .models import Customer


class CustomerAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_customer(self):
        response = self.client.post('/api/customers/', {
            'name': 'John Doe',
            'email': 'john@example.com'
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Customer.objects.count(), 1)

    def test_get_customers(self):
        Customer.objects.create(name='Jane Doe', email='jane@example.com')
        response = self.client.get('/api/customers/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_get_customer_detail(self):
        customer = Customer.objects.create(name='Bob', email='bob@example.com')
        response = self.client.get(f'/api/customers/{customer.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Bob')
