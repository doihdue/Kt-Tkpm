import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Book, Category, Review, SearchBehaviorEvent, SearchUserProfile
from .serializers import BookSerializer, ReviewSerializer, CategorySerializer
from .typo_search_model import predict_query_book_scores


SYNONYM_MAP = {
    "ai": ["tri tue nhan tao", "artificial intelligence"],
    "machine": ["ml", "hoc may"],
    "python": ["py"],
    "business": ["kinh doanh", "startup"],
    "history": ["lich su"],
}

PHRASE_SYNONYMS = {
    "tri tue nhan tao": ["ai", "artificial intelligence"],
    "hoc may": ["machine", "ml"],
    "kinh doanh": ["business", "startup"],
}

EVENT_STRENGTH = {
    "search": 0.2,
    "click": 0.8,
    "add_to_cart": 1.2,
    "purchase": 2.0,
}


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFD", str(value).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_set(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if token}


def _query_book_overlap_ratio(query_tokens: set[str], book: Book) -> float:
    if not query_tokens:
        return 0.0
    book_tokens = _token_set(
        f"{book.title} {book.author} {book.category.name if book.category else ''} {book.description or ''}"
    )
    if not book_tokens:
        return 0.0
    return len(query_tokens & book_tokens) / float(len(query_tokens))


def _ordered_token_ratio(query_tokens: List[str], book: Book) -> float:
    if not query_tokens:
        return 0.0
    title = _normalize_text(book.title)
    if not title:
        return 0.0
    joined = " ".join(query_tokens)
    if joined and joined in title:
        return 1.0

    idx = 0
    matched = 0
    for token in query_tokens:
        pos = title.find(token, idx)
        if pos >= 0:
            matched += 1
            idx = pos + len(token)
    return matched / float(len(query_tokens))


def _event_weight(event_type: str) -> float:
    return {
        "search": 0.2,
        "click": 1.0,
        "add_to_cart": 1.8,
        "purchase": 2.6,
    }.get(event_type, 0.2)


def _behavior_signal_maps(query_tokens: set[str]) -> tuple[Dict[int, float], Dict[int, float]]:
    # Use recent events to keep ranking adaptive and lightweight.
    events = SearchBehaviorEvent.objects.order_by("-created_at")[:4000]

    global_scores: Dict[int, float] = defaultdict(float)
    query_scores: Dict[int, float] = defaultdict(float)

    for event in events:
        weight = _event_weight(event.event_type)
        event_book_ids: List[int] = []
        if event.book_id is not None:
            event_book_ids.append(int(event.book_id))
        if isinstance(event.book_ids, list):
            for bid in event.book_ids:
                if isinstance(bid, int):
                    event_book_ids.append(bid)

        if not event_book_ids:
            continue

        event_tokens = _token_set(event.query or "")
        query_related = bool(query_tokens and event_tokens and (query_tokens & event_tokens))

        for bid in event_book_ids:
            global_scores[bid] += weight
            if query_related:
                query_scores[bid] += (1.25 * weight)

    if global_scores:
        max_global = max(global_scores.values())
        if max_global > 0:
            for bid in list(global_scores.keys()):
                global_scores[bid] = global_scores[bid] / max_global

    if query_scores:
        max_query = max(query_scores.values())
        if max_query > 0:
            for bid in list(query_scores.keys()):
                query_scores[bid] = query_scores[bid] / max_query

    return dict(global_scores), dict(query_scores)


def _build_corpus_vocabulary(books: List[Book]) -> set[str]:
    vocab: set[str] = set()
    for book in books:
        category = book.category.name if book.category else ""
        combined = f"{book.title} {book.author} {category} {book.description or ''}"
        vocab.update(_token_set(combined))
    return {token for token in vocab if len(token) >= 2}


def _best_token_correction(token: str, vocabulary: set[str]) -> str:
    if token in vocabulary or not vocabulary:
        return token

    best = token
    best_score = 0.0
    for word in vocabulary:
        if word[0] != token[0]:
            continue
        ratio = SequenceMatcher(None, token, word).ratio()
        if ratio > best_score:
            best_score = ratio
            best = word
    return best if best_score >= 0.82 else token


def rewrite_query(query: str, books: List[Book]) -> tuple[str, set[str]]:
    normalized_query = _normalize_text(query)
    tokens = list(_token_set(normalized_query))
    if not tokens:
        return query, set()

    vocabulary = _build_corpus_vocabulary(books)
    corrected_tokens = [_best_token_correction(token, vocabulary) for token in tokens]
    rewritten_tokens = list(corrected_tokens)
    expanded_tokens = set(corrected_tokens)
    for phrase, synonyms in PHRASE_SYNONYMS.items():
        if phrase in normalized_query:
            for synonym in synonyms:
                synonym_tokens = _token_set(synonym)
                expanded_tokens.update(synonym_tokens)
                rewritten_tokens.extend(list(synonym_tokens))
    for token in corrected_tokens:
        for synonym in SYNONYM_MAP.get(token, []):
            expanded_tokens.update(_token_set(synonym))

    rewritten = " ".join(list(dict.fromkeys(rewritten_tokens)))
    return rewritten, expanded_tokens


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _upsert_user_profile_behavior(
    customer_id: int,
    event_type: str,
    query: str = "",
    book_id: Optional[int] = None,
    book_ids: Optional[List[int]] = None,
) -> None:
    if customer_id <= 0:
        return

    strength = EVENT_STRENGTH.get(event_type, 0.2)
    profile, _ = SearchUserProfile.objects.get_or_create(customer_id=customer_id)
    token_weights: Dict[str, float] = dict(profile.token_weights or {})
    item_weights: Dict[str, float] = dict(profile.book_weights or {})

    for token in _token_set(query):
        token_weights[token] = token_weights.get(token, 0.0) + (0.5 * strength)

    all_book_ids: List[int] = []
    if book_id is not None:
        all_book_ids.append(book_id)
    if book_ids:
        all_book_ids.extend([bid for bid in book_ids if isinstance(bid, int)])

    for bid in all_book_ids:
        key = str(bid)
        item_weights[key] = item_weights.get(key, 0.0) + strength

    profile.token_weights = token_weights
    profile.book_weights = item_weights
    profile.save(update_fields=["token_weights", "book_weights", "updated_at"])


def _fuzzy_score(query: str, book: Book, deep_score: float = 0.0) -> float:
    q_norm = _normalize_text(query)
    if not q_norm:
        return 0.0

    title = _normalize_text(book.title)
    author = _normalize_text(book.author)
    category = _normalize_text(book.category.name if book.category else "")
    description = _normalize_text(book.description or "")[:300]

    ratio_title = SequenceMatcher(None, q_norm, title).ratio()
    ratio_author = SequenceMatcher(None, q_norm, author).ratio()
    ratio_category = SequenceMatcher(None, q_norm, category).ratio()
    ratio_desc = SequenceMatcher(None, q_norm, description).ratio() if description else 0.0

    # Compare query against each title word to tolerate typo in short terms.
    best_word_ratio = 0.0
    for word in title.split(" "):
        if not word:
            continue
        best_word_ratio = max(best_word_ratio, SequenceMatcher(None, q_norm, word).ratio())

    q_tokens = _token_set(q_norm)
    book_tokens = _token_set(" ".join([title, author, category, description]))
    overlap_ratio = 0.0
    if q_tokens:
        overlap_ratio = len(q_tokens & book_tokens) / float(len(q_tokens))

    lexical_score = (
        (0.45 * ratio_title)
        + (0.18 * ratio_author)
        + (0.12 * ratio_category)
        + (0.10 * ratio_desc)
        + (0.10 * best_word_ratio)
        + (0.05 * overlap_ratio)
    )
    if deep_score <= 0:
        return lexical_score

    # Blend lexical and deep similarity to tolerate misspelled queries.
    return (0.65 * lexical_score) + (0.35 * float(deep_score))


def _personalization_boost(customer_id: Optional[int], book: Book, query_tokens: set[str]) -> float:
    if not customer_id:
        return 0.0

    profile = SearchUserProfile.objects.filter(customer_id=customer_id).first()
    if not profile:
        return 0.0

    token_weights = profile.token_weights or {}
    book_weights = profile.book_weights or {}

    book_text_tokens = _token_set(
        f"{book.title} {book.author} {book.category.name if book.category else ''} {book.description or ''}"
    )
    token_boost = 0.0
    if query_tokens:
        weighted_match = 0.0
        for token in query_tokens | book_text_tokens:
            weighted_match += _safe_float(token_weights.get(token))
        token_boost = min(weighted_match / 20.0, 1.0)

    behavior_boost = min(_safe_float(book_weights.get(str(book.id))) / 5.0, 1.0)
    return (0.6 * behavior_boost) + (0.4 * token_boost)


def _fuzzy_filter_books(queryset, query: str, customer_id: Optional[int] = None):
    normalized_original_query = _normalize_text(query)
    original_token_count = len(_token_set(normalized_original_query))
    has_phrase_synonym_intent = any(phrase in normalized_original_query for phrase in PHRASE_SYNONYMS)

    books = list(queryset.select_related("category"))
    rewritten_query, expanded_tokens = rewrite_query(query, books)
    core_query_tokens = _token_set(rewritten_query)
    core_query_token_list = [token for token in rewritten_query.split(" ") if token]
    query_tokens = expanded_tokens or core_query_tokens
    token_count = len(core_query_tokens)
    min_score = 0.22 if token_count <= 2 else 0.28

    deep_scores = predict_query_book_scores(rewritten_query, books)
    global_behavior_scores, query_behavior_scores = _behavior_signal_maps(core_query_tokens)

    ranked = []
    for book in books:
        fuzzy_score = _fuzzy_score(rewritten_query, book, deep_scores.get(book.id, 0.0))
        overlap_ratio = _query_book_overlap_ratio(core_query_tokens, book)
        ordered_ratio = _ordered_token_ratio(core_query_token_list, book)
        score = fuzzy_score
        score += 0.20 * ordered_ratio
        score += 0.14 * global_behavior_scores.get(book.id, 0.0)
        score += 0.20 * query_behavior_scores.get(book.id, 0.0)
        score += 0.18 * _personalization_boost(customer_id, book, query_tokens)

        # For longer specific queries, force lexical overlap to reduce noisy matches.
        if original_token_count >= 4 and not has_phrase_synonym_intent and overlap_ratio < 0.34 and fuzzy_score < 0.72:
            continue
        if score >= min_score:
            ranked.append((score, overlap_ratio, book))

    ranked.sort(key=lambda row: row[0], reverse=True)

    # Intent-aware narrowing: if query is specific and top match is strong, keep only near-top matches.
    if original_token_count >= 4 and not has_phrase_synonym_intent and ranked:
        top_score = ranked[0][0]
        if top_score >= 0.70:
            narrowed = []
            for score, overlap_ratio, book in ranked:
                if score < (top_score - 0.14):
                    continue
                if overlap_ratio < 0.30 and score < 0.78:
                    continue
                narrowed.append((score, overlap_ratio, book))
            ranked = narrowed

    return [book for _, _, book in ranked[:60]], rewritten_query


class BookListCreate(APIView):
    def get(self, request):
        queryset = Book.objects.all().order_by('title')
        title = request.query_params.get('title', None)
        category = request.query_params.get('category', None)
        customer_id = request.query_params.get('customer_id')
        rewritten_query = ""

        try:
            customer_id_int = int(customer_id) if customer_id else None
        except ValueError:
            customer_id_int = None
        
        if category:
            queryset = queryset.filter(category__id=category)

        if title:
            title = title.strip()
            if title:
                exact_queryset = queryset.filter(
                    Q(title__icontains=title)
                    | Q(author__icontains=title)
                    | Q(description__icontains=title)
                    | Q(category__name__icontains=title)
                ).distinct()
                if exact_queryset.exists():
                    queryset = exact_queryset.order_by('title')
                else:
                    queryset, rewritten_query = _fuzzy_filter_books(queryset, title, customer_id=customer_id_int)

        serializer = BookSerializer(queryset, many=True)
        if title and customer_id_int:
            result_ids = [int(item.get("id")) for item in serializer.data if item.get("id") is not None][:30]
            SearchBehaviorEvent.objects.create(
                customer_id=customer_id_int,
                event_type="search",
                query=rewritten_query or title,
                book_ids=result_ids,
                metadata={"raw_query": title},
            )
            _upsert_user_profile_behavior(
                customer_id=customer_id_int,
                event_type="search",
                query=rewritten_query or title,
                book_ids=result_ids[:5],
            )
        return Response(serializer.data)

    def post(self, request):
        serializer = BookSerializer(data=request.data)
        if serializer.is_valid():
            book = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BookDetail(APIView):
    def get(self, request, pk):
        try:
            book = Book.objects.get(pk=pk)
        except Book.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = BookSerializer(book)
        return Response(serializer.data)

    def put(self, request, pk):
        try:
            book = Book.objects.get(pk=pk)
        except Book.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = BookSerializer(book, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        try:
            book = Book.objects.get(pk=pk)
        except Book.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        book.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookReviewListCreate(APIView):
    def get(self, request, book_pk):
        try:
            book = Book.objects.get(pk=book_pk)
        except Book.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reviews = book.reviews.all()
        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data)

    def post(self, request, book_pk):
        try:
            book = Book.objects.get(pk=book_pk)
        except Book.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        data = request.data.copy()
        data['book'] = book.id
        serializer = ReviewSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReviewDetail(APIView):
    def delete(self, request, book_pk, review_id):
        try:
            review = Review.objects.get(pk=review_id, book_id=book_pk)
        except Review.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CategoryListCreate(APIView):
    def get(self, request):
        categories = Category.objects.all().order_by('name')
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CategoryDetail(APIView):
    def get_object(self, pk):
        try:
            return Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return None

    def get(self, request, pk):
        category = self.get_object(pk)
        if category is None: return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = CategorySerializer(category)
        return Response(serializer.data)

    def put(self, request, pk):
        category = self.get_object(pk)
        if category is None: return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = CategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        category = self.get_object(pk)
        if category is None: return Response(status=status.HTTP_404_NOT_FOUND)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SearchEventTrack(APIView):
    def post(self, request):
        customer_id_raw = request.data.get("customer_id")
        event_type = str(request.data.get("event_type") or "").strip().lower()
        query = str(request.data.get("query") or "").strip()
        raw_book_id = request.data.get("book_id")
        raw_book_ids = request.data.get("book_ids")

        if event_type not in {"search", "click", "add_to_cart", "purchase"}:
            return Response({"detail": "Unsupported event_type"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer_id = int(customer_id_raw)
        except (TypeError, ValueError):
            return Response({"detail": "customer_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        book_id: Optional[int] = None
        if raw_book_id is not None:
            try:
                book_id = int(raw_book_id)
            except (TypeError, ValueError):
                book_id = None

        book_ids: List[int] = []
        if isinstance(raw_book_ids, list):
            for value in raw_book_ids:
                try:
                    book_ids.append(int(value))
                except (TypeError, ValueError):
                    continue

        SearchBehaviorEvent.objects.create(
            customer_id=customer_id,
            event_type=event_type,
            query=query,
            book_id=book_id,
            book_ids=book_ids,
            metadata={},
        )
        _upsert_user_profile_behavior(
            customer_id=customer_id,
            event_type=event_type,
            query=query,
            book_id=book_id,
            book_ids=book_ids,
        )

        return Response({"status": "ok"})
