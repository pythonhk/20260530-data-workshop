from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

SUBMISSION_FEATURES = [
    "origin_station",
    "destination_station",
    "district",
    "transport_type",
    "transport_detail",
    "mode",
    "service_level",
    "operator",
    "day_of_week",
    "is_holiday",
    "weather_condition",
    "country_code",
]

FIXED_MODEL_CONFIG = {
    "max_iter": 300,
    "learning_rate": 0.05,
    "max_depth": 6,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "early_stopping": True,
    "n_iter_no_change": 20,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the fixed workshop model on a cleaned candidate submission."
    )
    parser.add_argument("--input", required=True, help="Path to the cleaned CSV.")
    parser.add_argument(
        "--labels",
        help="Optional labels CSV with record_id and delay_risk for local dry runs.",
    )
    parser.add_argument(
        "--target-col",
        default="delay_risk",
        help="Target column name. Default: delay_risk.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.20,
        help="Fraction reserved for the local validation split. Default: 0.20.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed. Default: 42.",
    )
    return parser.parse_args()


def load_dataset(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"record_id": str})


def attach_labels_if_needed(
    df: pd.DataFrame,
    labels_path: str | None,
    target_col: str,
) -> pd.DataFrame:
    if target_col in df.columns:
        return df
    if labels_path is None:
        return df
    if "record_id" not in df.columns:
        raise ValueError("--labels requires the cleaned input to contain record_id")

    labels = load_dataset(labels_path)
    required = {"record_id", target_col}
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"labels file is missing columns: {sorted(missing)}")
    if labels["record_id"].duplicated().any():
        raise ValueError("labels file contains duplicate record_id values")

    merged = df.merge(
        labels[["record_id", target_col]],
        on="record_id",
        how="left",
        validate="one_to_one",
    )
    if merged[target_col].isna().any():
        raise ValueError("labels file does not cover every cleaned record_id")
    return merged


def prepare_training_frame(
    df: pd.DataFrame,
    target_col: str,
) -> tuple[pd.DataFrame, pd.Series]:
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' was not found.")

    missing = [column for column in SUBMISSION_FEATURES if column not in df.columns]
    if missing:
        raise ValueError(f"Cleaned CSV is missing columns: {missing}")

    working = df[[*SUBMISSION_FEATURES, target_col]].copy()
    working[target_col] = pd.to_numeric(working[target_col], errors="coerce")
    working = working.dropna(subset=[target_col])

    x = normalize_model_features(working[SUBMISSION_FEATURES])
    y = working[target_col].astype(int)
    return x, y


def normalize_model_features(df: pd.DataFrame) -> pd.DataFrame:
    converted = df.copy()
    for column in converted.columns:
        if pd.api.types.is_numeric_dtype(converted[column]):
            continue
        if pd.api.types.is_bool_dtype(converted[column]):
            continue

        numeric_version = pd.to_numeric(converted[column], errors="coerce")
        if numeric_version.notna().mean() >= 0.8:
            converted[column] = numeric_version
        else:
            converted[column] = (
                converted[column].astype("string").fillna("__MISSING__").astype(str)
            )
    return converted


def build_pipeline(x: pd.DataFrame, random_state: int) -> Pipeline:
    numeric_columns = x.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical_columns = [
        column for column in x.columns if column not in numeric_columns
    ]

    transformers = []
    if numeric_columns:
        transformers.append(("numeric", "passthrough", numeric_columns))
    if categorical_columns:
        transformers.append(
            (
                "categorical",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    encoded_missing_value=-2,
                ),
                categorical_columns,
            )
        )

    return Pipeline(
        steps=[
            ("preprocessor", ColumnTransformer(transformers=transformers)),
            (
                "model",
                HistGradientBoostingClassifier(
                    random_state=random_state,
                    **FIXED_MODEL_CONFIG,
                ),
            ),
        ]
    )


def split_training_frame(
    x: pd.DataFrame,
    y: pd.Series,
    test_size: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    split_index = max(1, min(len(x) - 1, int(len(x) * (1 - test_size))))
    return (
        x.iloc[:split_index].reset_index(drop=True),
        x.iloc[split_index:].reset_index(drop=True),
        y.iloc[:split_index].reset_index(drop=True),
        y.iloc[split_index:].reset_index(drop=True),
    )


def evaluate_model(
    pipeline: Pipeline,
    x_train: pd.DataFrame,
    x_eval: pd.DataFrame,
    y_train: pd.Series,
    y_eval: pd.Series,
) -> dict[str, float]:
    pipeline.fit(x_train, y_train)
    predictions = pipeline.predict(x_eval)
    probabilities = pipeline.predict_proba(x_eval)[:, 1]
    return {
        "f1_score": f1_score(y_eval, predictions),
        "roc_auc": roc_auc_score(y_eval, probabilities),
    }


def main() -> None:
    args = parse_args()
    df = load_dataset(args.input)
    df = attach_labels_if_needed(df, args.labels, args.target_col)
    if "record_id" in df.columns:
        df = df.sort_values("record_id").reset_index(drop=True)

    x, y = prepare_training_frame(df, args.target_col)
    x_train, x_eval, y_train, y_eval = split_training_frame(x, y, args.test_size)
    pipeline = build_pipeline(x_train, random_state=args.random_state)
    metrics = evaluate_model(pipeline, x_train, x_eval, y_train, y_eval)

    summary = {
        "input": args.input,
        "target_col": args.target_col,
        "evaluation_mode": "ordered_record_split",
        "feature_cols": SUBMISSION_FEATURES,
        "model_config": FIXED_MODEL_CONFIG,
        "train_rows": int(len(x_train)),
        "test_rows": int(len(x_eval)),
        "f1_score": round(metrics["f1_score"], 4),
        "roc_auc": round(metrics["roc_auc"], 4),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
