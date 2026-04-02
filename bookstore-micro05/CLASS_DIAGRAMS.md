# Class Diagrams by Service

## api-gateway

No explicit class definitions were found in this service. The gateway is function-based.

## auth-service

```mermaid
classDiagram
    class LoginRequest {
      +username: str
      +password: str
    }

    class TokenResponse {
      +access_token: str
      +token_type: str = bearer
      +expires_in: int
      +user: dict
    }

    LoginRequest -- TokenResponse : used in /auth/login
```

## customer-service

```mermaid
classDiagram
    class Customer {
      +id: int
      +name: str
      +username: str
      +password: str
      +email: str
      +phone_number: str?
    }

    class Address {
      +id: int
      +customer_id: int
      +recipient_name: str
      +phone_number: str
      +address_line: str
      +city: str
      +province: str
      +is_default: bool
      +save()
    }

    class AddressSerializer
    class CustomerSerializer {
      +addresses: AddressSerializer[]
      +create(validated_data)
    }

    Customer "1" --> "0..*" Address : addresses
    AddressSerializer ..> Address : serializes
    CustomerSerializer ..> Customer : serializes
    CustomerSerializer ..> AddressSerializer : nested
```

## cart-service

```mermaid
classDiagram
    class Cart {
      +id: int
      +customer_id: int (unique)
    }

    class CartItem {
      +id: int
      +cart_id: int
      +book_id: int
      +quantity: int
    }

    class CartItemSerializer
    class CartSerializer {
      +items: CartItemSerializer[]
    }

    Cart "1" --> "0..*" CartItem : items
    CartItemSerializer ..> CartItem : serializes
    CartSerializer ..> Cart : serializes
    CartSerializer ..> CartItemSerializer : nested
```

## book-service

```mermaid
classDiagram
    class Category {
      +id: int
      +name: str
      +description: str
    }

    class Book {
      +id: int
      +title: str
      +author: str
      +category_id: int?
      +price: decimal
      +image_url: str?
      +description: str
      +stock: int
    }

    class Review {
      +id: int
      +book_id: int
      +customer_id: int
      +rating: int
      +comment: str
      +created_at: datetime
    }

    class CategorySerializer
    class ReviewSerializer
    class BookSerializer {
      +average_rating
      +get_average_rating(obj)
    }

    Category "1" --> "0..*" Book : books
    Book "1" --> "0..*" Review : reviews
    CategorySerializer ..> Category
    ReviewSerializer ..> Review
    BookSerializer ..> Book
    BookSerializer ..> Category
```

## staff-service

```mermaid
classDiagram
    class Staff {
      +id: int
      +name: str
      +username: str?
      +password: str?
      +email: str
      +role: str
      +is_active: bool
    }

    class StaffSerializer {
      +create(validated_data)
      +update(instance, validated_data)
    }

    StaffSerializer ..> Staff : serializes
```

## catalog-service

```mermaid
classDiagram
    class CatalogItemRow {
      +id: int
      +name: str
      +description: str?
    }

    class CatalogItem {
      +id: int
      +name: str
      +description: str?
    }

    class CatalogItemCreate {
      +name: str
      +description: str?
    }

    CatalogItemCreate --> CatalogItemRow : create row
    CatalogItemRow --> CatalogItem : map to response
```

## order-service

```mermaid
classDiagram
    class OrderRow {
      +id: str
      +order_code: str
      +customer_id: int
      +items: text(json)
      +total_price: float
      +status: str
      +payment_method: str?
      +shipping_address: str?
      +payment_id: str?
      +shipping_id: str?
    }

    class OrderItem {
      +book_id: int
      +quantity: int
      +price_at_purchase: float
      +book_title: str
    }

    class Order {
      +id: str
      +order_code: str
      +customer_id: int
      +items: OrderItem[]
      +total_price: float
      +status: str
      +payment_method: str?
      +shipping_address: str?
      +payment_id: str?
      +shipping_id: str?
      +simulate_payment_failure: bool
      +simulate_shipping_failure: bool
      +simulate_confirm_failure: bool
    }

    Order "1" --> "1..*" OrderItem : items
    Order --> OrderRow : persist/restore
```

## payment-service

```mermaid
classDiagram
    class PaymentRequest {
      +order_id: str
      +amount: float
      +method: str
    }
```

## shipping-service

```mermaid
classDiagram
    class ShipmentRequest {
      +order_id: str
      +address: str
    }
```

## manager-service

```mermaid
classDiagram
    class ManagementTaskRow {
      +id: str
      +title: str
      +priority: str
      +status: str
      +created_at: datetime
    }

    class ManagementTask {
      +id: str
      +title: str
      +priority: str
      +status: str
    }

    class CreateTaskRequest {
      +title: str
      +priority: str
    }

    CreateTaskRequest --> ManagementTaskRow : create row
    ManagementTaskRow --> ManagementTask : map to response
```

## comment-rate-service

```mermaid
classDiagram
    class CommentRateRow {
      +id: str
      +book_id: int
      +customer_id: int
      +rating: int
      +comment: str
      +created_at: datetime
    }

    class CommentRateCreate {
      +book_id: int
      +customer_id: int
      +rating: int(1..5)
      +comment: str
    }

    class CommentRate {
      +id: str
      +book_id: int
      +customer_id: int
      +rating: int
      +comment: str
      +created_at: datetime?
    }

    CommentRate --|> CommentRateCreate
    CommentRateCreate --> CommentRateRow : create row
    CommentRateRow --> CommentRate : map to response
```

## recommender-ai-service

```mermaid
classDiagram
    class RecommendationEventRow {
      +id: str
      +customer_id: int
      +viewed_book_ids: text(json)
      +recommendations: text(json)
      +created_at: datetime
    }

    class UserPreferenceRow {
      +customer_id: int
      +viewed_book_ids: text(json)
      +updated_at: datetime
    }

    class RecommendRequest {
      +customer_id: int
      +viewed_book_ids: int[]
    }

    class Recommendation {
      +book_id: int
      +score: float
      +reason: str
    }

    RecommendRequest --> Recommendation : generate list
    Recommendation --> RecommendationEventRow : saved as json
    RecommendRequest --> UserPreferenceRow : update preference
```
