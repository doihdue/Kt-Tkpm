from django.db import models


class Cart(models.Model):
    customer_id = models.IntegerField(unique=True)

    def __str__(self):
        return f"Cart({self.customer_id})"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    book_id = models.IntegerField()
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"Item(book={self.book_id}, qty={self.quantity})"
