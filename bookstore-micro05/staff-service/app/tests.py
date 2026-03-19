from django.test import TestCase
from rest_framework.test import APIClient
from .models import Staff


class StaffAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_staff(self):
        response = self.client.post('/api/staff/', {
            'name': 'John Doe',
            'email': 'john@example.com',
            'role': 'manager'
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Staff.objects.count(), 1)

    def test_get_staff(self):
        Staff.objects.create(name='Jane Doe', email='jane@example.com', role='admin')
        response = self.client.get('/api/staff/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_update_staff(self):
        staff = Staff.objects.create(name='Original', email='orig@example.com', role='staff')
        response = self.client.put(f'/api/staff/{staff.id}/', {'role': 'manager'}, format='json')
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertEqual(staff.role, 'manager')
