from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Staff

class StaffSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = Staff
        fields = ['id', 'name', 'username', 'email', 'password', 'role', 'is_active']

    def create(self, validated_data):
        raw_password = validated_data.pop('password', None)
        if raw_password:
            validated_data['password'] = make_password(raw_password)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        raw_password = validated_data.pop('password', None)
        if raw_password:
            instance.password = make_password(raw_password)
        return super().update(instance, validated_data)