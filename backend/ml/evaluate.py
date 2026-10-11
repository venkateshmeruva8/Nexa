import os
import pickle
from typing import Dict, Any
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report
)

try:
    from .train import load_and_validate_dataset, MODEL_PATH, DATASET_PATH
    from .classifier import build_features
except ImportError:
    from train import load_and_validate_dataset, MODEL_PATH, DATASET_PATH
    from classifier import build_features


def load_model_artifact(model_path: str = MODEL_PATH) -> Dict[str, Any]:
    """Loads the pickled model bundle artifact from disk."""
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model artifact not found at {model_path}. Train the model first.")
    with open(model_path, "rb") as f:
        return pickle.load(f)


def evaluate_model(
    model_path: str = MODEL_PATH,
    dataset_path: str = DATASET_PATH,
    test_size: float = 0.20,
    random_state: int = 42
) -> Dict[str, Any]:
    """
    Evaluates the saved model against the held-out test set.
    Calculates Accuracy, Macro/Weighted Precision, Recall, F1, and Confusion Matrix.
    """
    model_bundle = load_model_artifact(model_path)
    word_vec = model_bundle["word_vectorizer"]
    char_vec = model_bundle["char_vectorizer"]
    classifier = model_bundle["classifier"]

    texts, intents = load_and_validate_dataset(dataset_path)

    # Recreate the exact held-out test set split
    _, x_test, _, y_test = train_test_split(
        texts,
        intents,
        test_size=test_size,
        random_state=random_state,
        stratify=intents
    )

    x_test_vec, _, _ = build_features(
        x_test,
        word_vectorizer=word_vec,
        char_vectorizer=char_vec,
        fit=False
    )

    y_pred = classifier.predict(x_test_vec)

    labels = classifier.classes_
    cm = confusion_matrix(y_test, y_pred, labels=labels)

    metrics: Dict[str, Any] = {
        "total_samples": len(texts),
        "test_samples": len(x_test),
        "training_samples": len(texts) - len(x_test),
        "num_classes": len(labels),
        "classes": list(labels),
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "macro_precision": float(precision_score(y_test, y_pred, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_test, y_pred, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
        "weighted_precision": float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
        "weighted_recall": float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
        "weighted_f1": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
        "confusion_matrix": cm,
        "classification_report": classification_report(y_test, y_pred, labels=labels, zero_division=0)
    }

    return metrics


if __name__ == "__main__":
    results = evaluate_model()
    print("=" * 50)
    print("        NEXA INTENT CLASSIFIER EVALUATION")
    print("=" * 50)
    print(f"Total Samples:       {results['total_samples']}")
    print(f"Training Samples:    {results['training_samples']}")
    print(f"Test Samples:        {results['test_samples']}")
    print(f"Number of Classes:   {results['num_classes']}")
    print("-" * 50)
    print(f"Accuracy:            {results['accuracy'] * 100:.2f}%")
    print(f"Macro Precision:     {results['macro_precision'] * 100:.2f}%")
    print(f"Macro Recall:        {results['macro_recall'] * 100:.2f}%")
    print(f"Macro F1-Score:      {results['macro_f1'] * 100:.2f}%")
    print(f"Weighted Precision:  {results['weighted_precision'] * 100:.2f}%")
    print(f"Weighted Recall:     {results['weighted_recall'] * 100:.2f}%")
    print(f"Weighted F1-Score:   {results['weighted_f1'] * 100:.2f}%")
    print("-" * 50)
    print("Classification Report:")
    print(results["classification_report"])
    print("Confusion Matrix shape:", results["confusion_matrix"].shape)
