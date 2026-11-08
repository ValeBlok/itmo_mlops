import argparse
import hashlib
import json
from pathlib import Path

import joblib
from sklearn.pipeline import FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer


def document_text(document: dict) -> str:
    return " ".join([document["title"], document["body"], " ".join(document["tags"] * 2)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=Path, default=Path("data/documents.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()

    raw = args.documents.read_bytes()
    documents = json.loads(raw)
    texts = [document_text(document) for document in documents]
    vectorizer = FeatureUnion([
        ("word", TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True)),
        ("char", TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
    ])
    matrix = vectorizer.fit_transform(texts)

    args.output.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "matrix": matrix, "documents": documents}, args.output / "search-index.joblib")
    metadata = {
        "artifact_schema": "runbook-search-index/v1",
        "model_name": "runbook-hybrid-tfidf",
        "model_type": "tfidf-word-char-cosine",
        "index_version": hashlib.sha256(raw).hexdigest()[:12],
        "corpus_sha256": hashlib.sha256(raw).hexdigest(),
        "documents": len(documents),
        "features": int(matrix.shape[1]),
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
