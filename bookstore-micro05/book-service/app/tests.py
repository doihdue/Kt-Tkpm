from django.test import TestCase
from rest_framework.test import APIClient
from .models import Book


class BookAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_book(self):
        response = self.client.post('/api/books/', {
            'title': 'Test Book',
            'author': 'Test Author',
            'price': 29.99,
            'stock': 10
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Book.objects.count(), 1)

    def test_get_books(self):
        Book.objects.create(title='Book 1', author='Author 1', price=20.00)
        response = self.client.get('/api/books/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_update_book(self):
        book = Book.objects.create(title='Original', author='Author', price=15.00, stock=5)
        response = self.client.put(f'/api/books/{book.id}/', {'price': 25.00}, format='json')
        self.assertEqual(response.status_code, 200)
        book.refresh_from_db()
        self.assertEqual(book.price, 25.00)
