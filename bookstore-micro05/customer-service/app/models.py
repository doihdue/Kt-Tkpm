from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=255)
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.name


class Address(models.Model):
    customer = models.ForeignKey(Customer, related_name='addresses', on_delete=models.CASCADE)
    recipient_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    address_line = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    province = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Địa chỉ'
        verbose_name_plural = 'Địa chỉ'

    def __str__(self):
        return f"{self.recipient_name}, {self.address_line}, {self.city}, {self.province}"

    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(customer=self.customer, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)