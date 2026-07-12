from sentence_transformers import SentenceTransformer
import numpy as np

MODEL_NAME = 'all-MiniLM-L6-v2'
model = None


def get_model() -> SentenceTransformer:
    global model

    if model is None:
        print("Loading local embedding model... (This is completely free and runs on your CPU)")
        model = SentenceTransformer(MODEL_NAME)

    return model


def get_embedding(text: str) -> list[float]:
    # Takes a  summary and converts it into a mathematical vector
    embedding = get_model().encode(text)

    # Convert it to a Python list so we can save it to our DB easily
    return embedding.tolist()


def calculate_similarity(vector1: list[float], vector2: list[float]) -> float:
    """
    Compares two vectors using Cosine Similarity.
    Returns a score from 0.0 (completely different) to 1.0 (exact same meaning).
    """
    v1 = np.array(vector1)
    v2 = np.array(vector2)

    similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

    return float(similarity)
