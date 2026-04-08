import os
import random
import re
import unicodedata
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


DEFAULT_MODEL_PATH = os.getenv(
    "TYPO_SEARCH_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "models", "typo_search_model"),
)


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFD", str(value).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_book_text(book: object) -> str:
    title = normalize_text(getattr(book, "title", ""))
    author = normalize_text(getattr(book, "author", ""))
    category_name = ""
    category = getattr(book, "category", None)
    if category is not None:
        category_name = normalize_text(getattr(category, "name", ""))
    description = normalize_text(getattr(book, "description", ""))
    return " ".join([title, author, category_name, description]).strip()


@lru_cache(maxsize=1)
def _load_model(model_path: str = DEFAULT_MODEL_PATH):
    if not os.path.exists(model_path):
        return None

    try:
        import tensorflow as tf

        return tf.keras.models.load_model(model_path, compile=False)
    except Exception:
        return None


def predict_query_book_scores(query: str, books: Sequence[object]) -> Dict[int, float]:
    model = _load_model()
    if model is None:
        return {}

    q_norm = normalize_text(query)
    if not q_norm:
        return {}

    candidates: List[Tuple[int, str]] = []
    for book in books:
        bid = getattr(book, "id", None)
        if bid is None:
            continue
        text_value = _build_book_text(book)
        if not text_value:
            continue
        candidates.append((int(bid), text_value))

    if not candidates:
        return {}

    queries = np.array([q_norm] * len(candidates), dtype=object)
    docs = np.array([text_value for _, text_value in candidates], dtype=object)

    try:
        predictions = model.predict({"query": queries, "candidate": docs}, verbose=0)
        scores = [float(x) for x in np.array(predictions).reshape(-1).tolist()]
    except Exception:
        return {}

    out: Dict[int, float] = {}
    for (book_id, _), score in zip(candidates, scores):
        out[book_id] = max(0.0, min(1.0, score))
    return out


def _random_typo(text: str) -> str:
    if not text:
        return text

    chars = list(text)
    if len(chars) == 1:
        return chars[0]

    op = random.choice(["delete", "swap", "replace", "insert"])
    idx = random.randrange(0, len(chars))
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 "

    if op == "delete" and len(chars) > 1:
        del chars[idx]
    elif op == "swap" and len(chars) > 1 and idx < len(chars) - 1:
        chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    elif op == "replace":
        chars[idx] = random.choice(alphabet)
    elif op == "insert":
        chars.insert(idx, random.choice(alphabet))

    return normalize_text("".join(chars))


def _make_training_pairs(base_texts: Sequence[str], typo_per_text: int = 5) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    normalized = [normalize_text(text) for text in base_texts]
    normalized = [text for text in normalized if text]
    unique_texts = list(dict.fromkeys(normalized))

    if len(unique_texts) < 2:
        raise ValueError("Need at least 2 distinct texts to train typo model")

    left: List[str] = []
    right: List[str] = []
    labels: List[float] = []

    for text_value in unique_texts:
        left.append(text_value)
        right.append(text_value)
        labels.append(1.0)

        for _ in range(max(1, typo_per_text)):
            typo = _random_typo(text_value)
            if typo and typo != text_value:
                left.append(typo)
                right.append(text_value)
                labels.append(1.0)

    negatives = len(labels)
    for _ in range(negatives):
        a, b = random.sample(unique_texts, 2)
        left.append(a)
        right.append(b)
        labels.append(0.0)

    left_arr = np.array(left, dtype=object)
    right_arr = np.array(right, dtype=object)
    labels_arr = np.array(labels, dtype=np.float32)
    return left_arr, right_arr, labels_arr


def train_typo_model(
    base_texts: Sequence[str],
    model_path: str = DEFAULT_MODEL_PATH,
    epochs: int = 8,
    batch_size: int = 128,
    typo_per_text: int = 5,
) -> Dict[str, float]:
    import tensorflow as tf

    random.seed(42)
    np.random.seed(42)
    tf.random.set_seed(42)

    q_texts, c_texts, labels = _make_training_pairs(base_texts, typo_per_text=typo_per_text)
    corpus = np.concatenate([q_texts, c_texts], axis=0)

    max_tokens = 7000
    seq_len = 64

    vectorizer = tf.keras.layers.TextVectorization(
        max_tokens=max_tokens,
        output_mode="int",
        output_sequence_length=seq_len,
        split="character",
    )
    vectorizer.adapt(corpus)

    string_input = tf.keras.layers.Input(shape=(1,), dtype=tf.string)
    x = vectorizer(string_input)
    x = tf.keras.layers.Embedding(max_tokens, 48, mask_zero=True)(x)
    x = tf.keras.layers.Bidirectional(tf.keras.layers.GRU(48))(x)
    x = tf.keras.layers.Dense(64, activation="relu")(x)
    encoder = tf.keras.Model(string_input, x, name="typo_encoder")

    query_input = tf.keras.layers.Input(shape=(1,), dtype=tf.string, name="query")
    cand_input = tf.keras.layers.Input(shape=(1,), dtype=tf.string, name="candidate")

    query_vec = encoder(query_input)
    cand_vec = encoder(cand_input)

    mult = tf.keras.layers.Multiply()([query_vec, cand_vec])
    merged = tf.keras.layers.Concatenate()([query_vec, cand_vec, mult])

    dense = tf.keras.layers.Dense(128, activation="relu")(merged)
    dense = tf.keras.layers.Dropout(0.25)(dense)
    dense = tf.keras.layers.Dense(64, activation="relu")(dense)
    output = tf.keras.layers.Dense(1, activation="sigmoid")(dense)

    model = tf.keras.Model(inputs=[query_input, cand_input], outputs=output, name="typo_search_model")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="binary_crossentropy",
        metrics=[tf.keras.metrics.AUC(name="auc"), "accuracy"],
    )

    history = model.fit(
        {"query": q_texts, "candidate": c_texts},
        labels,
        epochs=max(1, int(epochs)),
        batch_size=max(16, int(batch_size)),
        validation_split=0.15,
        verbose=1,
    )

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    model.save(model_path, save_format="tf")

    final_loss = float(history.history["loss"][-1])
    final_auc = float(history.history.get("auc", [0.0])[-1])
    final_acc = float(history.history.get("accuracy", [0.0])[-1])

    return {
        "samples": float(labels.shape[0]),
        "loss": final_loss,
        "auc": final_auc,
        "accuracy": final_acc,
    }
