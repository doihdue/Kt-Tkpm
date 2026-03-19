from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.hashers import check_password
from .models import Staff
from .serializers import StaffSerializer

class StaffViewSet(viewsets.ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer

class AuthViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'])
    def token(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        try:
            staff = Staff.objects.get(username=username)
            if check_password(password, staff.password):
                return Response(StaffSerializer(staff).data)
        except Staff.DoesNotExist:
            pass
        return Response({'error': 'Sai tai khoan hoac mat khau'}, status=status.HTTP_401_UNAUTHORIZED)