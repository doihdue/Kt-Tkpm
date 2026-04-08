from django.test import TestCase
from rest_framework.test import APIClient
from .models import Book, Category, SearchBehaviorEvent, SearchUserProfile


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

    def test_search_tolerates_typo_in_title(self):
        Book.objects.create(title='Python Engineering', author='Alice', price=20.00, stock=5)
        Book.objects.create(title='Clean Code', author='Bob', price=30.00, stock=5)

        response = self.client.get('/api/books/?title=pythno')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item['title'] == 'Python Engineering' for item in response.data))

    def test_search_tolerates_typo_with_category_filter(self):
        tech = Category.objects.create(name='Technology')
        fiction = Category.objects.create(name='Fiction')
        Book.objects.create(title='Machine Learning Basics', author='Carol', category=tech, price=50.00, stock=3)
        Book.objects.create(title='Mystery Tale', author='Dave', category=fiction, price=15.00, stock=8)

        response = self.client.get(f'/api/books/?title=machne&category={tech.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item['title'] == 'Machine Learning Basics' for item in response.data))
        self.assertFalse(any(item['title'] == 'Mystery Tale' for item in response.data))

    def test_search_supports_synonym_rewrite(self):
        Book.objects.create(title='AI Fundamentals', author='Alice', price=20.00, stock=5)

        response = self.client.get('/api/books/?title=tri tue nhan tao')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item['title'] == 'AI Fundamentals' for item in response.data))

    def test_track_search_event_updates_profile(self):
        payload = {
            'customer_id': 7,
            'event_type': 'click',
            'query': 'python',
            'book_id': 11,
            'book_ids': [],
        }
        response = self.client.post('/api/search/events/', payload, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SearchBehaviorEvent.objects.count(), 1)
        profile = SearchUserProfile.objects.filter(customer_id=7).first()
        self.assertIsNotNone(profile)
        self.assertGreater(float(profile.book_weights.get('11', 0.0)), 0.0)

    def test_long_typo_query_prefers_target_book_without_noise(self):
        Book.objects.create(title='De Men Phieu Luu Ky', author='To Hoai', price=69.00, stock=10)
        Book.objects.create(title='Tu Tot Den Vi Dai', author='Jim Collins', price=128.00, stock=10)
        Book.objects.create(title='Dac Nhan Tam', author='Dale Carnegie', price=86.00, stock=10)

        response = self.client.get('/api/books/?title=de me.nn phieu luw ky')
        self.assertEqual(response.status_code, 200)

        titles = [item['title'] for item in response.data]
        self.assertIn('De Men Phieu Luu Ky', titles)
        self.assertFalse('Tu Tot Den Vi Dai' in titles and 'Dac Nhan Tam' in titles)

    def test_behavior_events_boost_relevant_book(self):
        target = Book.objects.create(title='Clean Architecture', author='Robert Martin', price=200.00, stock=5)
        Book.objects.create(title='Poetry Collection', author='Anon', price=50.00, stock=5)

        # Simulate users searching and converting on the target book.
        for _ in range(4):
            SearchBehaviorEvent.objects.create(customer_id=1, event_type='search', query='clean architecture', book_ids=[target.id], metadata={})
            SearchBehaviorEvent.objects.create(customer_id=1, event_type='click', query='clean architecture', book_id=target.id, metadata={})
            SearchBehaviorEvent.objects.create(customer_id=1, event_type='purchase', query='clean architecture', book_id=target.id, metadata={})

        response = self.client.get('/api/books/?title=clean architecture')
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)
        self.assertEqual(response.data[0]['title'], 'Clean Architecture')
