# HKPUG Data Cleaning Tournament

This is the candidate-facing bundle for the workshop tournament.

Teams submit cleaner code. The trusted GitHub Action runs that cleaner against
the public train and test feature files, trains the fixed model, evaluates
against hidden test labels, and updates the global leaderboard.

## Files You Edit

- `submission/clean.py`
- `pyproject.toml` and `uv.lock` if your cleaner needs extra public packages

For an official PR, encrypt and submit only:

- `submission/clean.py.cms`
- `submission/manifest.json`
- `submission/manifest.sig`
- `pyproject.toml`
- `uv.lock`

## Required Cleaner Output Fields

Both cleaned CSV outputs must include one row per official `record_id` and these
feature columns:

- `origin_station`
- `destination_station`
- `district`
- `transport_type`
- `transport_detail`
- `mode`
- `service_level`
- `operator`
- `day_of_week`
- `is_holiday`
- `weather_condition`
- `country_code`

Do not include `delay_risk` in cleaned outputs. Public train labels are stored
separately in `data/train_labels.csv`; hidden test labels are encrypted.

## Local Dry Run

From the repo root:

```bash
uv sync --locked
uv run python submission/clean.py \
  --train-input data/train_features.csv \
  --train-output artifacts/cleaned_train.csv
uv run python train_submission.py \
  --input artifacts/cleaned_train.csv \
  --labels data/train_labels.csv
```

The official scorer will also run your cleaner on `data/test_features.csv`.
You do not need test labels for the local dry run.

## Official Submission

After receiving your team private key, copy `submission/manifest.example.json`
to `submission/manifest.json`, set your assigned `team_id`, then run:

```bash
submission/encrypt_submission.sh /path/to/team_private_key.pem
```

The script encrypts `submission/clean.py`, writes its SHA-256 digest into the
manifest, and signs the manifest with your team private key.

## Warm-Up Note

The messy dataset still contains strongly corrupted numeric fields such as:

- `fare_hkd`
- `distance_km`
- `scheduled_duration_min`

These numeric fields are useful as a warm-up cleaning task, but they are not part of the fixed workshop submission feature set.
