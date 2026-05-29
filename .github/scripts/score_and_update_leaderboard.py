from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from sklearn.metrics import f1_score, roc_auc_score

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from train_submission import (
    SUBMISSION_FEATURES,
    build_pipeline,
    normalize_model_features,
)


TEAM_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")
TARGET_COLUMN = "delay_risk"


@dataclass(frozen=True)
class ScoreResult:
    team_id: str
    score: float
    f1_score: float
    submitted_at: str
    run_id: str
    pr_number: str
    daily_attempt_count: int
    max_daily_attempts: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleaned-train", required=True, type=Path)
    parser.add_argument("--cleaned-test", required=True, type=Path)
    parser.add_argument("--train-labels", required=True, type=Path)
    parser.add_argument("--test-labels", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--leaderboard", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--max-daily-attempts", required=True, type=int)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--metric-label", default="ROC-AUC")
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype={"record_id": str})


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def validate_manifest(manifest: dict) -> str:
    team_id = manifest.get("team_id")
    if not isinstance(team_id, str) or not TEAM_ID_RE.fullmatch(team_id):
        raise ValueError("manifest.json must contain a valid team_id")
    if manifest.get("code_path") != "submission/clean.py.cms":
        raise ValueError("manifest.json code_path must be submission/clean.py.cms")
    return team_id


def prepare_cleaned_train(frame: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    if "record_id" not in frame.columns:
        raise ValueError("cleaned_train must contain record_id")
    if TARGET_COLUMN in frame.columns:
        raise ValueError(f"cleaned_train must not contain {TARGET_COLUMN}")
    if frame["record_id"].duplicated().any():
        raise ValueError("cleaned_train contains duplicate record_id values")

    label_ids = set(labels["record_id"].astype(str))
    actual_ids = set(frame["record_id"].astype(str))
    unknown_ids = actual_ids - label_ids
    if unknown_ids:
        raise ValueError("cleaned_train contains unknown record_id values")
    missing_features = [
        column for column in SUBMISSION_FEATURES if column not in frame.columns
    ]
    if missing_features:
        raise ValueError(f"cleaned_train is missing columns: {missing_features}")
    if len(actual_ids) < max(100, int(len(label_ids) * 0.5)):
        raise ValueError("cleaned_train dropped too many labeled training rows")
    return frame.copy()


def prepare_cleaned_test(frame: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    if "record_id" not in frame.columns:
        raise ValueError("cleaned_test must contain record_id")
    if TARGET_COLUMN in frame.columns:
        raise ValueError(f"cleaned_test must not contain {TARGET_COLUMN}")
    if frame["record_id"].duplicated().any():
        raise ValueError("cleaned_test contains duplicate record_id values")

    expected = labels["record_id"].astype(str).tolist()
    actual_ids = set(frame["record_id"].astype(str))
    if actual_ids != set(expected):
        raise ValueError(
            "cleaned_test must contain exactly one row for every test record_id"
        )
    missing_features = [
        column for column in SUBMISSION_FEATURES if column not in frame.columns
    ]
    if missing_features:
        raise ValueError(f"cleaned_test is missing columns: {missing_features}")
    return frame.set_index("record_id").loc[expected].reset_index()


def score_submission(
    cleaned_train: pd.DataFrame,
    cleaned_test: pd.DataFrame,
    train_labels: pd.DataFrame,
    test_labels: pd.DataFrame,
) -> tuple[float, float]:
    train = prepare_cleaned_train(cleaned_train, train_labels)
    test = prepare_cleaned_test(cleaned_test, test_labels)

    labels_by_id = train_labels.set_index("record_id")[TARGET_COLUMN]
    test_labels_by_id = test_labels.set_index("record_id")[TARGET_COLUMN]
    y_train = labels_by_id.loc[train["record_id"]].astype(int)
    y_test = test_labels_by_id.loc[test["record_id"]].astype(int)
    if y_train.nunique() < 2:
        raise ValueError("train labels must contain at least two classes")
    if y_test.nunique() < 2:
        raise ValueError("test labels must contain at least two classes")

    features = normalize_model_features(
        pd.concat(
            [train[SUBMISSION_FEATURES], test[SUBMISSION_FEATURES]],
            ignore_index=True,
        )
    )
    X_train = features.iloc[: len(train)].reset_index(drop=True)
    X_test = features.iloc[len(train) :].reset_index(drop=True)
    model = build_pipeline(X_train, random_state=20260530)
    model.fit(X_train, y_train)
    probabilities = model.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    return float(roc_auc_score(y_test, probabilities)), float(
        f1_score(y_test, predictions)
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str, timezone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone)


def load_leaderboard(path: Path, metric_label: str) -> dict:
    if path.is_file():
        data = json.loads(path.read_text())
    else:
        data = {}
    data.setdefault("schema_version", 2)
    data["metric_label"] = metric_label
    data.setdefault("entries", [])
    data.setdefault("submissions", [])
    return data


def count_daily_attempts(
    submissions: list[dict], team_id: str, now: str, timezone: ZoneInfo
) -> int:
    today = parse_time(now, timezone).date()
    count = 0
    for submission in submissions:
        if submission.get("team_id") != team_id:
            continue
        submitted_at = submission.get("submitted_at")
        if not isinstance(submitted_at, str):
            continue
        if parse_time(submitted_at, timezone).date() == today:
            count += 1
    return count


def ensure_daily_attempt_available(
    submissions: list[dict],
    team_id: str,
    now: str,
    timezone: ZoneInfo,
    max_daily_attempts: int,
) -> int:
    if max_daily_attempts < 1:
        raise ValueError("max_daily_attempts must be at least 1")

    daily_attempts = count_daily_attempts(submissions, team_id, now, timezone)
    if daily_attempts >= max_daily_attempts:
        raise ValueError(
            f"{team_id} has already used {daily_attempts}/{max_daily_attempts} "
            "scored attempts today"
        )
    return daily_attempts + 1


def build_entries(submissions: list[dict]) -> list[dict]:
    by_team: dict[str, list[dict]] = {}
    for submission in submissions:
        by_team.setdefault(str(submission["team_id"]), []).append(submission)

    entries = []
    for team_id, values in by_team.items():
        best = max(
            values, key=lambda item: (float(item["score"]), item["submitted_at"])
        )
        entries.append(
            {
                "team_id": team_id,
                "score": float(best["score"]),
                "submitted_at": best["submitted_at"],
                "best_submitted_at": best["submitted_at"],
                "latest_submitted_at": max(item["submitted_at"] for item in values),
                "attempts": len(values),
                "run_id": best.get("run_id", ""),
                "pr_number": best.get("pr_number", ""),
            }
        )
    return sorted(entries, key=lambda item: (-float(item["score"]), item["team_id"]))


def append_result(
    leaderboard: dict,
    result: ScoreResult,
) -> None:
    submission = {
        "team_id": result.team_id,
        "score": result.score,
        "f1_score": result.f1_score,
        "submitted_at": result.submitted_at,
        "run_id": result.run_id,
        "pr_number": result.pr_number,
    }
    leaderboard["submissions"].append(submission)
    leaderboard["entries"] = build_entries(leaderboard["submissions"])
    leaderboard["updated_at"] = result.submitted_at


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(data, indent=2)}\n")


def main() -> None:
    args = parse_args()
    timezone = ZoneInfo(args.timezone)
    submitted_at = utc_now()
    manifest = read_json(args.manifest)
    team_id = validate_manifest(manifest)
    leaderboard = load_leaderboard(args.leaderboard, args.metric_label)

    daily_attempt_count = ensure_daily_attempt_available(
        leaderboard["submissions"],
        team_id,
        submitted_at,
        timezone,
        args.max_daily_attempts,
    )

    score, f1 = score_submission(
        read_csv(args.cleaned_train),
        read_csv(args.cleaned_test),
        read_csv(args.train_labels),
        read_csv(args.test_labels),
    )
    result = ScoreResult(
        team_id=team_id,
        score=score,
        f1_score=f1,
        submitted_at=submitted_at,
        run_id=args.run_id,
        pr_number=args.pr_number,
        daily_attempt_count=daily_attempt_count,
        max_daily_attempts=args.max_daily_attempts,
    )
    append_result(leaderboard, result)
    write_json(args.leaderboard, leaderboard)
    write_json(args.result, result.__dict__)


if __name__ == "__main__":
    main()
