from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

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

OUTPUT_COLUMNS = ["record_id", *SUBMISSION_FEATURES]

STATION_ALIASES = {
    "central": "Central Station",
    "central station": "Central Station",
    "central stn": "Central Station",
    "wanchai": "Wan Chai",
    "wan chai": "Wan Chai",
    "causewaybay": "Causeway Bay",
    "causeway bay": "Causeway Bay",
    "cwb": "Causeway Bay",
    "admiralty": "Admiralty",
    "adm": "Admiralty",
    "tst": "Tsim Sha Tsui",
    "tsim sha tsui": "Tsim Sha Tsui",
    "mongkok": "Mong Kok",
    "mong kok": "Mong Kok",
    "mk": "Mong Kok",
    "shatin": "Sha Tin",
    "sha tin": "Sha Tin",
    "tsuenwan": "Tsuen Wan",
    "tsuen wan": "Tsuen Wan",
    "kennedy town": "Kennedy Town",
    "kennedytown": "Kennedy Town",
    "north point": "North Point",
    "northpoint": "North Point",
}

DISTRICT_BY_ORIGIN = {
    "Central Station": "Central and Western",
    "Wan Chai": "Wan Chai",
    "Causeway Bay": "Wan Chai",
    "Admiralty": "Central and Western",
    "Tsim Sha Tsui": "Yau Tsim Mong",
    "Mong Kok": "Yau Tsim Mong",
    "Sha Tin": "Sha Tin",
    "Tsuen Wan": "Tsuen Wan",
    "Kennedy Town": "Central and Western",
    "North Point": "Eastern",
}


def clean(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _clean_frame(train), _clean_frame(test)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    if "record_id" not in cleaned.columns:
        raise ValueError("input data must contain record_id")

    cleaned["record_id"] = cleaned["record_id"].astype(str)
    for column in ["origin_station", "destination_station"]:
        if column in cleaned.columns:
            cleaned[column] = cleaned[column].map(_normalize_station)

    if "origin_station" in cleaned.columns:
        cleaned["district"] = cleaned["origin_station"].map(DISTRICT_BY_ORIGIN)

    if "encoded_transport" in cleaned.columns:
        parts = cleaned["encoded_transport"].map(_parse_transport).apply(pd.Series)
        for column in ["transport_type", "transport_detail", "mode", "service_level", "operator"]:
            cleaned[column] = parts[column]

    if "day_of_week" in cleaned.columns:
        cleaned["day_of_week"] = cleaned["day_of_week"].map(_normalize_day)
    if "weather_condition" in cleaned.columns:
        cleaned["weather_condition"] = cleaned["weather_condition"].map(_normalize_weather)
    if "country_code" in cleaned.columns:
        cleaned["country_code"] = cleaned["country_code"].map(_normalize_country)

    for column in OUTPUT_COLUMNS:
        if column not in cleaned.columns:
            cleaned[column] = pd.NA

    cleaned = cleaned.drop_duplicates(subset=["record_id"], keep="first")
    return cleaned[OUTPUT_COLUMNS].reset_index(drop=True)


def _normalize_station(value: object) -> object:
    if pd.isna(value):
        return value
    text = re.sub(r"[_:-]+", " ", str(value)).strip().lower()
    text = re.sub(r"\s+", " ", text)
    for alias, canonical in STATION_ALIASES.items():
        if alias in text:
            return canonical
    return str(value).strip()


def _parse_transport(value: object) -> dict[str, object]:
    text = "" if pd.isna(value) else str(value).lower()
    text = text.replace("__", " ").replace("_", " ").replace("-", " ")

    transport_type = _first_match(text, ["bus", "tram", "ferry"])
    transport_detail = _first_match(text, ["airport", "night", "crossharbour", "cross harbour"])
    mode = _first_match(text, ["local", "express"])
    service_level = _first_match(text, ["standard", "premium"])
    operator = _first_match(text, ["kmb", "ctb", "hkkf"])

    return {
        "transport_type": transport_type,
        "transport_detail": "crossharbour" if transport_detail == "cross harbour" else (transport_detail or "general"),
        "mode": mode,
        "service_level": service_level,
        "operator": operator.upper() if isinstance(operator, str) else pd.NA,
    }


def _first_match(text: str, choices: list[str]) -> str | None:
    return next((choice for choice in choices if choice in text), None)


def _normalize_day(value: object) -> object:
    if pd.isna(value):
        return value
    days = {
        "mon": "Mon",
        "tue": "Tue",
        "wed": "Wed",
        "thu": "Thu",
        "fri": "Fri",
        "sat": "Sat",
        "sun": "Sun",
    }
    return days.get(str(value).strip().lower(), value)


def _normalize_weather(value: object) -> object:
    if pd.isna(value):
        return value
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    if "heavy" in text and "rain" in text:
        return "Heavy Rain"
    if "rain" in text or text in {"wx r", "rn v2"}:
        return "Rain"
    if "cloud" in text or "cld" in text:
        return "Cloudy"
    if "sun" in text or text in {"wx s"}:
        return "Sunny"
    return value


def _normalize_country(value: object) -> object:
    if pd.isna(value):
        return value
    text = str(value).strip().lower()
    if text in {"hk", "hkg", "852", "geo::hkg", "geo::852", "territory-hk", "hk-zone"}:
        return "HK"
    if text in {"mo", "mac"}:
        return "MO"
    if text in {"cn", "chn"}:
        return "CN"
    return str(value).strip().upper()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-input", required=True)
    parser.add_argument("--train-output", required=True)
    parser.add_argument("--test-input")
    parser.add_argument("--test-output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train = pd.read_csv(args.train_input)
    cleaned_train = _clean_frame(train)
    Path(args.train_output).parent.mkdir(parents=True, exist_ok=True)
    cleaned_train.to_csv(args.train_output, index=False)

    if args.test_input or args.test_output:
        if not args.test_input or not args.test_output:
            raise ValueError("--test-input and --test-output must be provided together")
        test = pd.read_csv(args.test_input)
        cleaned_test = _clean_frame(test)
        Path(args.test_output).parent.mkdir(parents=True, exist_ok=True)
        cleaned_test.to_csv(args.test_output, index=False)


if __name__ == "__main__":
    main()
