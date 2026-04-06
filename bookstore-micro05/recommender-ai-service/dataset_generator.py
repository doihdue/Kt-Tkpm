"""
Advanced Dataset Generator for Recommender AI
Generates realistic book catalog and customer behavior patterns
"""

import json
import random
from typing import List, Dict, Tuple
from datetime import datetime, timedelta

# Vietnamese book data with realistic categories and descriptions
BOOK_TEMPLATES = {
    "Technology": [
        {
            "title_prefix": ["Python", "Java", "C++", "JavaScript", "Go", "Rust"],
            "title_middle": ["for", "with", "through", "mastering"],
            "title_suffix": ["Beginners", "Advanced Users", "Data Science", "Web Development", "Systems", "ML Engineers"],
            "author_first": ["Guido", "Bjarne", "Brendan", "Graydon", "Elixir", "Tim"],
            "author_last": ["Van Rossum", "Stroustrup", "Eich", "Hoare", "Workshop", "Peters"],
            "description_parts": [
                "Tìm hiểu lập trình từ cơ bản đến nâng cao",
                "Hướng dẫn chi tiết với ví dụ thực tế",
                "Best practices từ các chuyên gia công nghệ",
                "Framework và libraries phổ biến nhất",
                "Giải pháp tối ưu hiệu suất ứng dụng"
            ]
        }
    ],
    "Business": [
        {
            "title_prefix": ["The", "Startup", "Digital", "Business", "Growth"],
            "title_middle": ["Mindset", "Strategy", "Blueprint", "Playbook", "Guide"],
            "title_suffix": ["for Leaders", "in 2024", "to Scale", "Fundamentals", "Essentials"],
            "author_first": ["Warren", "Jack", "Simon", "Clayton", "Peter"],
            "author_last": ["Buffett", "Welch", "Sinek", "Christensen", "Drucker"],
            "description_parts": [
                "Chiến lược kinh doanh hiệu quả",
                "Xây dựng startup thành công",
                "Quản lý tài chính cá nhân",
                "Lãnh đạo đội nhóm chuyên nghiệp",
                "Đầu tư thông minh cho tương lai"
            ]
        }
    ],
    "Science": [
        {
            "title_prefix": ["The", "Brief", "Cosmos", "Universe", "Journey"],
            "title_middle": ["of", "through", "into", "beyond"],
            "title_suffix": ["Physics", "Biology", "Chemistry", "Astronomy", "Genetics"],
            "author_first": ["Stephen", "Carl", "Neil", "Brian", "Richard"],
            "author_last": ["Hawking", "Sagan", "deGrasse Tyson", "Greene", "Dawkins"],
            "description_parts": [
                "Khám phá bí ẩn của vũ trụ",
                "Những phát hiện khoa học đột phá",
                "Lịch sử và ứng dụng thực tế",
                "Giải thích khoa học dễ hiểu",
                "Gặp gỡ các nhà khoa học huyền thoại"
            ]
        }
    ],
    "Fiction": [
        {
            "title_prefix": ["The", "Shadow", "Lost", "Midnight", "Eternal"],
            "title_middle": ["of", "in", "at", "beyond"],
            "title_suffix": ["Mystery", "Castle", "Dreams", "Realm", "Kingdom"],
            "author_first": ["Emily", "Victor", "Charlotte", "Arthur", "George"],
            "author_last": ["Bronte", "Hugo", "Shelley", "Conan Doyle", "Orwell"],
            "description_parts": [
                "Câu chuyện đầy kịch tính và bí ẩn",
                "Hành trình tìm kiếm chân lý",
                "Tình yêu, chiến tranh và sự sống",
                "Các nhân vật sâu sắc và phức tạp",
                "Thế giới tưởng tượng đầy quyến rũ"
            ]
        }
    ],
    "Self-Help": [
        {
            "title_prefix": ["The", "Atomic", "Deep", "Digital", "Mindful"],
            "title_middle": ["Habits", "Work", "Thinking", "Minimalism", "Living"],
            "title_suffix": ["for Success", "in the Age", "to Thrive", "Mastery", "Freedom"],
            "author_first": ["James", "Cal", "Simon", "Arianna", "Tara"],
            "author_last": ["Clear", "Newport", "Sinek", "Huffington", "Brach"],
            "description_parts": [
                "Thay đổi cuộc sống thông qua thói quen",
                "Tập trung sâu vào công việc quan trọng",
                "Tìm thấy sự cân bằng và hạnh phúc",
                "Phát triển kỹ năng lãnh đạo bản thân",
                "Vượt qua giới hạn tâm lý"
            ]
        }
    ],
    "History": [
        {
            "title_prefix": ["The", "World", "Great", "Hidden", "Untold"],
            "title_middle": ["History of", "Wars of", "Leaders of", "Secrets of"],
            "title_suffix": ["Humanity", "the Century", "the World", "Ancient Times", "Modern Era"],
            "author_first": ["Will", "Yuval", "Doris", "Ian", "Malcolm"],
            "author_last": ["Durant", "Harari", "Kearns", "Morris", "Gladwell"],
            "description_parts": [
                "Những sự kiện lịch sử thay đổi thế giới",
                "Hất động những quyết định lịch sử",
                "Các nhân vật danh tiếng và tầm ảnh hưởng",
                "Bài học từ quá khứ cho hiện tại",
                "Sự phát triển của nền văn minh nhân loại"
            ]
        }
    ]
}

CATEGORIES = list(BOOK_TEMPLATES.keys())


def generate_book_title(category: str) -> str:
    """Generate a random book title based on category"""
    template = random.choice(BOOK_TEMPLATES[category])
    
    title_prefix = random.choice(template["title_prefix"])
    title_middle = random.choice(template["title_middle"])
    title_suffix = random.choice(template["title_suffix"])
    
    return f"{title_prefix} {title_middle} {title_suffix}"


def generate_book_author() -> str:
    """Generate a random author name"""
    first_names = ["James", "Sarah", "Michael", "Emma", "David", "Lisa", "Robert", "Jennifer",
                   "William", "Patricia", "Richard", "Linda", "Joseph", "Barbara", "Thomas"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                  "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson"]
    
    return f"{random.choice(first_names)} {random.choice(last_names)}"


def generate_book_price() -> float:
    """Generate realistic book price"""
    return round(random.uniform(15, 150), 2)


def generate_books(count: int = 2000) -> List[Dict]:
    """Generate a large catalog of realistic books"""
    books = []
    
    for i in range(1, count + 1):
        category = random.choice(CATEGORIES)
        template = BOOK_TEMPLATES[category][0]
        
        desc_parts = random.sample(template["description_parts"], k=random.randint(2, 3))
        description = ". ".join(desc_parts) + "."
        
        book = {
            "id": i,
            "title": generate_book_title(category),
            "author": generate_book_author(),
            "description": description,
            "category": category,
            "price": generate_book_price(),
            "rating": round(random.uniform(3.5, 5.0), 1),
            "published_year": random.randint(2000, 2024),
            "pages": random.randint(100, 800),
            "language": "Vietnamese"
        }
        books.append(book)
    
    return books


def generate_customer_behavior(books: List[Dict], num_customers: int = 300) -> Tuple[List[Dict], List[Dict]]:
    """
    Generate realistic customer behavior patterns
    Returns: (customer_profiles, interaction_events)
    """
    
    customer_profiles = []
    interaction_events = []
    
    # Define customer personas with different interests
    personas = [
        {
            "name": "Tech Enthusiast",
            "interests": ["Technology"],
            "view_count_range": (15, 40),
            "purchase_rate": 0.5,
            "budget": (30, 150)
        },
        {
            "name": "Business Professional",
            "interests": ["Business"],
            "view_count_range": (10, 30),
            "purchase_rate": 0.4,
            "budget": (20, 120)
        },
        {
            "name": "Science Nerd",
            "interests": ["Science"],
            "view_count_range": (20, 50),
            "purchase_rate": 0.45,
            "budget": (25, 140)
        },
        {
            "name": "Fiction Lover",
            "interests": ["Fiction"],
            "view_count_range": (25, 60),
            "purchase_rate": 0.55,
            "budget": (15, 100)
        },
        {
            "name": "Self-Improvement Seeker",
            "interests": ["Self-Help", "Business"],
            "view_count_range": (15, 35),
            "purchase_rate": 0.48,
            "budget": (20, 130)
        },
        {
            "name": "History Buff",
            "interests": ["History", "Fiction"],
            "view_count_range": (20, 45),
            "purchase_rate": 0.42,
            "budget": (20, 110)
        },
        {
            "name": "Curious Mind",
            "interests": CATEGORIES,  # Interested in everything
            "view_count_range": (30, 70),
            "purchase_rate": 0.5,
            "budget": (25, 150)
        }
    ]
    
    # Create customers with different profiles
    event_id = 0
    
    for customer_id in range(1, num_customers + 1):
        persona = random.choice(personas)
        
        customer = {
            "customer_id": customer_id,
            "name": f"Customer_{customer_id}",
            "persona": persona["name"],
            "interests": persona["interests"],
            "total_spent": 0.0,
            "purchase_count": 0
        }
        
        # Generate viewing behavior
        num_views = random.randint(persona["view_count_range"][0], persona["view_count_range"][1])
        viewed_books = set()
        purchased_books = set()
        
        # Select books based on interests
        category_books = {}
        for category in CATEGORIES:
            category_books[category] = [b for b in books if b["category"] == category]
        
        # Generate views
        for _ in range(num_views):
            category = random.choice(persona["interests"])
            available_books = [b for b in category_books[category] if b["id"] not in viewed_books]
            
            if available_books:
                book = random.choice(available_books)
                viewed_books.add(book["id"])
                
                # Record view event
                event = {
                    "event_id": event_id,
                    "customer_id": customer_id,
                    "book_id": book["id"],
                    "event_type": "view",
                    "timestamp": datetime.now() - timedelta(days=random.randint(1, 180)),
                    "rating_given": None
                }
                interaction_events.append(event)
                event_id += 1
        
        # Generate purchases (subset of viewed books)
        num_purchases = int(num_views * persona["purchase_rate"])
        for _ in range(num_purchases):
            if viewed_books:
                book_id = random.choice(list(viewed_books))
                if book_id not in purchased_books:
                    book = next(b for b in books if b["id"] == book_id)
                    purchased_books.add(book_id)
                    customer["total_spent"] += book["price"]
                    customer["purchase_count"] += 1
                    
                    # Record purchase event
                    event = {
                        "event_id": event_id,
                        "customer_id": customer_id,
                        "book_id": book_id,
                        "event_type": "purchase",
                        "timestamp": datetime.now() - timedelta(days=random.randint(1, 180)),
                        "rating_given": round(random.uniform(3.0, 5.0), 1) if random.random() > 0.4 else None
                    }
                    interaction_events.append(event)
                    event_id += 1
        
        customer["viewed_books"] = list(viewed_books)
        customer["purchased_books"] = list(purchased_books)
        customer_profiles.append(customer)
    
    return customer_profiles, interaction_events


def save_dataset(books: List[Dict], customers: List[Dict], events: List[Dict], output_dir: str = "."):
    """Save generated dataset to JSON files for training"""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # Save books
    with open(os.path.join(output_dir, "books.json"), "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2, default=str)
    
    # Save customers
    with open(os.path.join(output_dir, "customers.json"), "w", encoding="utf-8") as f:
        json.dump(customers, f, ensure_ascii=False, indent=2, default=str)
    
    # Save events
    with open(os.path.join(output_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"✓ Dataset saved to {output_dir}")
    print(f"  • Books: {len(books)}")
    print(f"  • Customers: {len(customers)}")
    print(f"  • Interaction events: {len(events)}")


if __name__ == "__main__":
    print("🚀 Generating Large-Scale Book Dataset...")
    
    # Generate books
    print("\n📚 Generating 2000+ books...")
    books = generate_books(2000)
    print(f"✓ Generated {len(books)} books")
    
    # Print sample books
    print("\nSample books:")
    for book in books[:3]:
        print(f"  • {book['title']} by {book['author']} (${book['price']}) - {book['category']}")
    
    # Generate customers and behavior
    print("\n👥 Generating 300+ customers with realistic behavior...")
    customers, events = generate_customer_behavior(books, num_customers=300)
    print(f"✓ Generated {len(customers)} customers")
    print(f"✓ Generated {len(events)} interaction events")
    
    # Print customer stats
    print("\nCustomer statistics:")
    avg_views = sum(len(c["viewed_books"]) for c in customers) / len(customers)
    avg_purchases = sum(c["purchase_count"] for c in customers) / len(customers)
    total_revenue = sum(c["total_spent"] for c in customers)
    print(f"  • Average views per customer: {avg_views:.1f}")
    print(f"  • Average purchases per customer: {avg_purchases:.1f}")
    print(f"  • Total revenue: ${total_revenue:,.2f}")
    
    # Save dataset
    save_dataset(books, customers, events, output_dir=".")
