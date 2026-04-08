import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "book_service.settings")

import django

django.setup()

from django.db.utils import OperationalError
from app.models import Book
from app.typo_search_model import train_typo_model, normalize_text


FALLBACK_TEXTS = [
    "python engineering",
    "machine learning basics",
    "deep learning practical guide",
    "clean code software craftsmanship",
    "data structures and algorithms",
    "history of world civilizations",
    "mystery detective novel",
    "startup business strategy",
    "ai fundamentals",
    "growth mindset self help",
]


def collect_training_texts() -> list[str]:
    texts: list[str] = []

    try:
        for book in Book.objects.select_related("category").all():
            title = normalize_text(book.title)
            author = normalize_text(book.author)
            category_name = normalize_text(book.category.name if book.category else "")
            description = normalize_text((book.description or "")[:180])

            if title:
                texts.append(title)
            if title and author:
                texts.append(f"{title} {author}")
            if title and category_name:
                texts.append(f"{title} {category_name}")
            if title and description:
                texts.append(f"{title} {description}")
    except OperationalError:
        texts = []

    if not texts:
        texts.extend(FALLBACK_TEXTS)

    # Keep deterministic unique order.
    return list(dict.fromkeys(texts))


def main() -> None:
    base_texts = collect_training_texts()
    if len(base_texts) < 2:
        raise SystemExit("Not enough book data to train typo model. Need at least 2 books.")

    model_path = os.getenv(
        "TYPO_SEARCH_MODEL_PATH",
        os.path.join("app", "models", "typo_search_model"),
    )

    metrics = train_typo_model(
        base_texts=base_texts,
        model_path=model_path,
        epochs=int(os.getenv("TYPO_TRAIN_EPOCHS", "8")),
        batch_size=int(os.getenv("TYPO_TRAIN_BATCH", "128")),
        typo_per_text=int(os.getenv("TYPO_PER_TEXT", "5")),
    )

    print("Typo model trained successfully")
    print(f"Model path: {model_path}")
    print(
        "Metrics: "
        f"samples={int(metrics['samples'])}, "
        f"loss={metrics['loss']:.4f}, "
        f"auc={metrics['auc']:.4f}, "
        f"accuracy={metrics['accuracy']:.4f}"
    )


if __name__ == "__main__":
    main()
