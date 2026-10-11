from typing import Any, Dict, Optional, Sequence, Tuple
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

try:
    from .normalizer import normalize_text
except ImportError:
    from normalizer import normalize_text


CONFIDENCE_THRESHOLD: float = 0.60
MARGIN_THRESHOLD: float = 0.12


def create_vectorizers() -> Tuple[TfidfVectorizer, TfidfVectorizer]:
    """
    Instantiates the word and character TF-IDF vectorizers with standard NEXA configurations.
    """
    word_vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        sublinear_tf=True,
        max_features=30000,
        max_df=0.98,
        lowercase=True,
        strip_accents="unicode"
    )

    char_vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        sublinear_tf=True,
        max_features=40000,
        max_df=0.995,
        lowercase=True,
        strip_accents="unicode"
    )

    return word_vectorizer, char_vectorizer


def create_classifier() -> LogisticRegression:
    """
    Instantiates the multi-class Logistic Regression classifier with standard NEXA parameters.
    """
    return LogisticRegression(
        max_iter=5000,
        C=10.0,
        class_weight="balanced",
        solver="lbfgs",
        random_state=42
    )


def build_features(
    texts: Sequence[str],
    word_vectorizer: Optional[TfidfVectorizer] = None,
    char_vectorizer: Optional[TfidfVectorizer] = None,
    fit: bool = False
) -> Tuple[Any, TfidfVectorizer, TfidfVectorizer]:
    """
    Extracts and combines word-level and character-level TF-IDF features using scipy.sparse.hstack.
    
    If fit=True and vectorizers are None, initializes and fits new vectorizers.
    If fit=False, transforms using the provided vectorizers.
    """
    normalized_texts = [normalize_text(t) for t in texts]

    if fit:
        if word_vectorizer is None or char_vectorizer is None:
            word_vectorizer, char_vectorizer = create_vectorizers()
        x_word = word_vectorizer.fit_transform(normalized_texts)
        x_char = char_vectorizer.fit_transform(normalized_texts)
    else:
        if word_vectorizer is None or char_vectorizer is None:
            raise ValueError("Both word_vectorizer and char_vectorizer must be provided when fit=False")
        x_word = word_vectorizer.transform(normalized_texts)
        x_char = char_vectorizer.transform(normalized_texts)

    combined_features = hstack([x_word, x_char])
    return combined_features, word_vectorizer, char_vectorizer


def predict_intent_details(
    text: str,
    model_bundle: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Infers intent, confidence, margin, and trust status for a single text input.
    Operates on a pre-trained model bundle dictionary.
    Handles empty/invalid input safely without crashing.
    """
    cleaned = normalize_text(text)
    if not cleaned or not model_bundle:
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "margin": 0.0,
            "trusted": False
        }

    word_vec = model_bundle.get("word_vectorizer")
    char_vec = model_bundle.get("char_vectorizer")
    classifier = model_bundle.get("classifier")

    if not word_vec or not char_vec or not classifier:
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "margin": 0.0,
            "trusted": False
        }

    try:
        x_word = word_vec.transform([cleaned])
        x_char = char_vec.transform([cleaned])
        x_features = hstack([x_word, x_char])

        probabilities = classifier.predict_proba(x_features)[0]
        sorted_indices = probabilities.argsort()[::-1]

        best_idx = sorted_indices[0]
        second_idx = sorted_indices[1] if len(sorted_indices) > 1 else best_idx

        intent = str(classifier.classes_[best_idx]).upper()
        confidence = float(probabilities[best_idx])
        second_confidence = float(probabilities[second_idx]) if len(sorted_indices) > 1 else 0.0

        margin = float(confidence - second_confidence)
        trusted = bool(confidence >= CONFIDENCE_THRESHOLD and margin >= MARGIN_THRESHOLD)

        return {
            "intent": intent,
            "confidence": confidence,
            "margin": margin,
            "trusted": trusted
        }
    except Exception:
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "margin": 0.0,
            "trusted": False
        }


def predict_intent(
    text: str,
    model_bundle: Optional[Dict[str, Any]] = None
) -> Tuple[str, float]:
    """
    Convenience wrapper returning (intent, confidence).
    """
    details = predict_intent_details(text, model_bundle=model_bundle)
    return details["intent"], details["confidence"]
