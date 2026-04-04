"""
AI Signal Filter — uses a trained ML model to reject low-quality trade signals.

Workflow:
  1. Collect training data from backtest / live trade results (training_data.csv)
  2. Train a RandomForest or LogisticRegression model → saved as model.pkl
  3. During live trading, call predict(features) before executing each trade

CLI usage:
  python ai_filter.py --train                     # train from training_data.csv
  python ai_filter.py --train --file custom.csv   # train from custom file
"""

import argparse
import logging
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

import config
from strategy import StrategyFeatures

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "rsi",
    "bb_distance_upper",
    "bb_distance_lower",
    "ema_trend",
    "tick_momentum",
    "volatility",
]


class AIFilter:
    """
    Wraps a trained sklearn classifier for trade signal filtering.
    Predicts 1 (take the trade) or 0 (skip).
    """

    def __init__(self, model_path: str | None = None, confidence_threshold: float | None = None):
        self.model_path = model_path or config.AI_MODEL_PATH
        self.confidence_threshold = confidence_threshold or config.AI_CONFIDENCE_THRESHOLD
        self.model = None
        self.scaler = None
        self._loaded = False

    def load(self) -> bool:
        """Load a previously trained model from disk."""
        if not os.path.exists(self.model_path):
            logger.warning("No model found at %s", self.model_path)
            return False
        try:
            with open(self.model_path, "rb") as f:
                bundle = pickle.load(f)
            self.model = bundle["model"]
            self.scaler = bundle.get("scaler")
            self._loaded = True
            logger.info("AI model loaded from %s", self.model_path)
            return True
        except Exception as e:
            logger.error("Failed to load model: %s", e)
            return False

    def predict(self, features: StrategyFeatures) -> int:
        """
        Returns 1 if the trade should be taken, 0 if it should be skipped.
        Falls back to 1 (allow) if no model is loaded.
        """
        if not self._loaded or self.model is None:
            return 1

        x = np.array(features.feature_array()).reshape(1, -1)
        if self.scaler is not None:
            x = self.scaler.transform(x)

        proba = self.model.predict_proba(x)[0]
        confidence = proba[1]  # probability of class 1 (profitable)

        if confidence >= self.confidence_threshold:
            logger.debug("AI filter PASS (confidence=%.3f)", confidence)
            return 1
        else:
            logger.debug("AI filter REJECT (confidence=%.3f)", confidence)
            return 0

    def predict_proba(self, features: StrategyFeatures) -> float:
        """Return raw probability of a profitable trade."""
        if not self._loaded or self.model is None:
            return 0.5
        x = np.array(features.feature_array()).reshape(1, -1)
        if self.scaler is not None:
            x = self.scaler.transform(x)
        return float(self.model.predict_proba(x)[0][1])


def train_model(
    data_path: str | None = None,
    model_path: str | None = None,
    model_type: str = "random_forest",
    test_size: float = 0.2,
) -> dict:
    """
    Train and save an AI filter model from labelled trade data.

    Returns a dict with training metrics.
    """
    data_path = data_path or config.TRAINING_DATA_CSV
    model_path = model_path or config.AI_MODEL_PATH

    logger.info("Loading training data from %s", data_path)
    df = pd.read_csv(data_path)

    required = FEATURE_COLUMNS + ["outcome"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in training data: {missing}")

    df = df.dropna(subset=required)
    if len(df) < 20:
        raise ValueError(
            f"Insufficient training data: {len(df)} rows (need at least 20)"
        )

    X = df[FEATURE_COLUMNS].values.astype(np.float64)
    y = df["outcome"].values.astype(int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    if model_type == "logistic_regression":
        model = LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=42
        )
    else:
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
        )

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=test_size, random_state=42, stratify=y
    )

    model.fit(X_train, y_train)

    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)

    cv_n = min(5, len(y_train) // 2) if len(y_train) >= 4 else 2
    cv_scores = cross_val_score(model, X_scaled, y, cv=cv_n, scoring="accuracy")

    bundle = {"model": model, "scaler": scaler, "feature_columns": FEATURE_COLUMNS}
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)

    metrics = {
        "model_type": model_type,
        "total_samples": len(df),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "train_accuracy": round(train_acc, 4),
        "test_accuracy": round(test_acc, 4),
        "cv_mean_accuracy": round(float(np.mean(cv_scores)), 4),
        "cv_std": round(float(np.std(cv_scores)), 4),
        "class_distribution": {
            "profitable": int(np.sum(y == 1)),
            "losing": int(np.sum(y == 0)),
        },
        "model_path": model_path,
    }

    if hasattr(model, "feature_importances_"):
        importances = dict(
            zip(FEATURE_COLUMNS, [round(v, 4) for v in model.feature_importances_])
        )
        metrics["feature_importances"] = importances

    logger.info("Model trained and saved to %s", model_path)
    logger.info("Metrics: %s", metrics)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="AI Signal Filter — Train or evaluate model")
    parser.add_argument("--train", action="store_true", help="Train a new model")
    parser.add_argument("--file", type=str, default=None, help="Path to training data CSV")
    parser.add_argument("--model-type", type=str, default="random_forest",
                        choices=["random_forest", "logistic_regression"])
    parser.add_argument("--output", type=str, default=None, help="Path to save model.pkl")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.train:
        metrics = train_model(
            data_path=args.file,
            model_path=args.output,
            model_type=args.model_type,
        )
        print("\n=== Training Results ===")
        for k, v in metrics.items():
            print(f"  {k}: {v}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
