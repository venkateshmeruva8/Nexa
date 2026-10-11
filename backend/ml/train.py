import os
import pickle
import csv
from typing import Dict, Any, Tuple, List
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

try:
    from .normalizer import normalize_text
    from .classifier import (
        CONFIDENCE_THRESHOLD,
        MARGIN_THRESHOLD,
        create_classifier,
        build_features,
    )
except ImportError:
    from normalizer import normalize_text
    from classifier import (
        CONFIDENCE_THRESHOLD,
        MARGIN_THRESHOLD,
        create_classifier,
        build_features,
    )

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH = os.path.join(BASE_DIR, "data", "intent_dataset.csv")
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "nexa_intent_model.pkl")


def load_and_validate_dataset(dataset_path: str = DATASET_PATH) -> Tuple[List[str], List[str]]:
    """
    Loads and validates the dataset from CSV.
    Safely skips empty or malformed rows.
    """
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset not found at {dataset_path}")

    texts: List[str] = []
    intents: List[str] = []

    with open(dataset_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "text" not in reader.fieldnames or "intent" not in reader.fieldnames:
            raise ValueError(f"Dataset must contain 'text' and 'intent' columns. Found: {reader.fieldnames}")

        for row in reader:
            raw_text = row.get("text", "")
            raw_intent = row.get("intent", "")

            cleaned_text = normalize_text(raw_text)
            cleaned_intent = raw_intent.strip().upper() if raw_intent else ""

            if cleaned_text and cleaned_intent:
                texts.append(cleaned_text)
                intents.append(cleaned_intent)

    if not texts:
        raise ValueError(f"No valid data rows found in {dataset_path}")

    return texts, intents


def train_model(
    dataset_path: str = DATASET_PATH,
    model_output_path: str = MODEL_PATH,
    test_size: float = 0.20,
    random_state: int = 42
) -> Dict[str, Any]:
    """
    Trains the dual TF-IDF + Logistic Regression intent classifier on the unified dataset.
    Saves the complete model bundle to disk.
    """
    texts, intents = load_and_validate_dataset(dataset_path)

    x_train, x_test, y_train, y_test = train_test_split(
        texts,
        intents,
        test_size=test_size,
        random_state=random_state,
        stratify=intents
    )

    # Fit feature extractors on training set and transform both sets
    x_train_vec, word_vec, char_vec = build_features(x_train, fit=True)
    x_test_vec, _, _ = build_features(
        x_test,
        word_vectorizer=word_vec,
        char_vectorizer=char_vec,
        fit=False
    )

    # Initialize and fit Logistic Regression classifier
    classifier = create_classifier()
    classifier.fit(x_train_vec, y_train)

    # Basic evaluation on test set
    y_pred = classifier.predict(x_test_vec)
    accuracy = float(accuracy_score(y_test, y_pred))
    macro_f1 = float(f1_score(y_test, y_pred, average="macro", zero_division=0))

    classes = sorted(list(set(intents)))

    model_bundle: Dict[str, Any] = {
        "word_vectorizer": word_vec,
        "char_vectorizer": char_vec,
        "classifier": classifier,
        "intents": classes,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "margin_threshold": MARGIN_THRESHOLD,
        "training_samples": len(x_train),
        "test_samples": len(x_test),
        "total_samples": len(texts),
        "num_classes": len(classes),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "random_state": random_state
    }

    os.makedirs(os.path.dirname(model_output_path), exist_ok=True)
    with open(model_output_path, "wb") as f:
        pickle.dump(model_bundle, f)

    return model_bundle


if __name__ == "__main__":
    bundle = train_model()
    print(f"Training completed successfully.")
    print(f"Artifact saved: {MODEL_PATH}")
    print(f"Training samples: {bundle['training_samples']}, Test samples: {bundle['test_samples']}")
    print(f"Accuracy: {bundle['accuracy'] * 100:.2f}%, Macro F1: {bundle['macro_f1'] * 100:.2f}%")
