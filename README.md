# HKPUG Data Cleaning Tournament

This is the candidate-facing bundle for the workshop tournament.

Teams submit cleaner code. The trusted GitHub Action runs that cleaner against
the public train and test feature files, trains the fixed model, evaluates
against hidden test labels, and updates the global leaderboard.

## Participant Workflow

1. Fork this repository.
2. Clone your fork:

```bash
git clone https://github.com/<your-github-username>/20260530-data-workshop.git
cd 20260530-data-workshop
uv sync --locked
```

3. Copy the manifest template:

```bash
cp submission/manifest.example.json submission/manifest.json
```

4. Edit `submission/manifest.json` and set `team_id` to your assigned team id.
5. Edit and test `submission/clean.py`.
6. Encrypt, sign, and open a PR to `pythonhk/20260530-data-workshop:main`.

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

`train_submission.py` trains the fixed model on the first 80% of the cleaned
training rows and reports validation metrics on the last 20%. To use a
different validation size, add for example `--test-size 0.30`.

The official scorer will also run your cleaner on `data/test_features.csv`.
You do not need test labels for the local dry run.

PR scores are different from local validation. The trusted GitHub Action trains
on your cleaned train output, evaluates on your cleaned `data/test_features.csv`
output, and uses hidden labels that are not in the public repo.

## Official Submission

After receiving your team private key, copy `submission/manifest.example.json`
to `submission/manifest.json`, set your assigned `team_id`, then run:

```bash
submission/encrypt_submission.sh /path/to/team_private_key.pem
```

On Windows PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\submission\encrypt_submission.ps1 C:\path\to\team_private_key.pem
```

If Windows says `OpenSSL was not found`, install
[Git for Windows](https://git-scm.com/download/win), reopen PowerShell, and run
the same command again.

The script encrypts `submission/clean.py`, writes its SHA-256 digest into the
manifest, and signs the manifest with your team private key.

## Warm-Up Note

The messy dataset still contains strongly corrupted numeric fields such as:

- `fare_hkd`
- `distance_km`
- `scheduled_duration_min`

These numeric fields are useful as a warm-up cleaning task, but they are not part of the fixed workshop submission feature set.
