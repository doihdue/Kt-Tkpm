from rest_framework import serializers
from .models import Customer, Address
from django.contrib.auth.hashers import make_password

# Di chuyển AddressSerializer lên trước để có thể sử dụng trong CustomerSerializer
class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = '__all__'

class CustomerSerializer(serializers.ModelSerializer):
    # Lồng thông tin địa chỉ vào dữ liệu khách hàng, chỉ đọc
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = ['id', 'name', 'username', 'email', 'phone_number', 'password', 'addresses']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        # Hash password before saving
        if 'password' in validated_data:
            validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)