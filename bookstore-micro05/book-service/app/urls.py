from django.urls import path
from .views import BookListCreate, BookDetail, BookReviewListCreate, ReviewDetail, CategoryListCreate, CategoryDetail

urlpatterns = [
    path('books/', BookListCreate.as_view()),
    path('books/<int:pk>/', BookDetail.as_view()),
    path('books/<int:book_pk>/reviews/', BookReviewListCreate.as_view()),
    path('books/<int:book_pk>/reviews/<int:review_id>/', ReviewDetail.as_view()),
    path('categories/', CategoryListCreate.as_view()),
    path('categories/<int:pk>/', CategoryDetail.as_view()),
]