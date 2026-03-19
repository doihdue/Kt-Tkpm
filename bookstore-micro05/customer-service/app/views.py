from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.contrib.auth.hashers import check_password
from django.db import transaction
import logging
from .models import Customer, Address
from .serializers import CustomerSerializer, AddressSerializer

logger = logging.getLogger(__name__)

class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer

    def create(self, request, *args, **kwargs):
        """Create customer with atomic transaction and explicit error handling."""
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                self.perform_create(serializer)
                headers = self.get_success_headers(serializer.data)
                return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Registration failed during post-create signal (e.g., cart creation): {e}", exc_info=True)
            return Response(
                {"error": "Không thể hoàn tất đăng ký do lỗi hệ thống. Vui lòng thử lại sau."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    @action(detail=True, methods=['get', 'post', 'put', 'patch', 'delete'], url_path='addresses(?:/(?P<address_id>[^/.]+))?')
    def addresses(self, request, pk=None, address_id=None):
        customer = self.get_object()
        
        if request.method == 'GET':
            # List all addresses for the customer
            addresses = customer.addresses.all()
            return Response(AddressSerializer(addresses, many=True).data)
        
        if request.method == 'POST':
            # Create a new address for the customer
            data = request.data.copy()
            data['customer'] = customer.id
            serializer = AddressSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # The following methods require an address_id
        if not address_id:
            return Response({'detail': 'Method requires an address ID.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

        try:
            address = Address.objects.get(id=address_id, customer=customer)
        except Address.DoesNotExist:
            return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method in ['PUT', 'PATCH']:
            # Use partial=True to allow updating a subset of fields,
            # which is what the API gateway does when setting a default address.
            serializer = AddressSerializer(address, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'DELETE':
            address.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

class AuthViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'])
    def token(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        try:
            customer = Customer.objects.get(username=username)
            if check_password(password, customer.password):
                return Response(CustomerSerializer(customer).data)
        except Customer.DoesNotExist:
            pass
            
        return Response({'error': 'Tài khoản hoặc mật khẩu không đúng'}, status=status.HTTP_401_UNAUTHORIZED)