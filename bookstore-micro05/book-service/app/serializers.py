from rest_framework import serializers
from .models import Book, Review, Category


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['id', 'book', 'customer_id', 'rating', 'comment', 'created_at']


class BookSerializer(serializers.ModelSerializer):
    average_rating = serializers.SerializerMethodField()
    category = serializers.CharField(source='category.name', read_only=True)
    category_pk = serializers.IntegerField(source='category.id', read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), source='category', write_only=True, required=False, allow_null=True)

    class Meta:
        model = Book
        fields = ['id', 'title', 'author', 'category', 'category_pk', 'category_id', 'price', 'description', 'stock', 'average_rating']

    def get_average_rating(self, obj):
        reviews = obj.reviews.all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 2)
