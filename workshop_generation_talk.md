# How The Workshop Dataset Was Generated

This note is a talk-ready summary of how the workshop dataset was built, how
the messy data was corrupted, and why the corruption needed to be layered rather
than simple.

## 1. Starting Point: A Clean Synthetic Dataset

The dataset starts from a clean synthetic transport table.

Each row represents one Hong Kong transport trip record with fields such as:

| Field group | Example fields | Purpose |
| --- | --- | --- |
| Trip identity | `record_id`, `route_id` | Identify a synthetic trip record |
| Location | `origin_station`, `destination_station`, `district` | Describe where the trip starts and ends |
| Transport | `encoded_transport` | Store transport type, detail, mode, service level, and operator in one encoded field |
| Calendar | `day_of_week`, `is_holiday`, `hour_of_day` | Describe timing context |
| Weather/location context | `weather_condition`, `country_code` | Add external trip context |
| Numeric trip values | `fare_hkd`, `distance_km`, `scheduled_duration_min` | Support warm-up cleaning tasks |
| Target | `delay_risk` | Classification target for delay risk |

The clean target is generated from a simulated `delay_minutes` value.

`delay_risk` is then defined as:

```text
delay_risk = 1 if delay_minutes >= 15 else 0
```

## 2. How The Target Signal Was Designed

The target is not random. It is influenced by several groups of fields:

| Signal group | Examples |
| --- | --- |
| Station signal | origin and destination station effects |
| District signal | district-level congestion effects |
| Weather signal | `Rain` and `Heavy Rain` increase delay risk |
| Transport signal | bus/tram/ferry, airport/night/crossharbour, local/express, standard/premium, operator |
| Calendar signal | weekend and holiday effects |
| Distance signal | longer distance has a small effect |

At generation time, the target is built through a simulated delay mean:

```text
delay_mean =
  3
  + calendar_effect
  + weather_effect
  + transport_effect
  + location_effect
  + distance_km * 0.02
```

Then random noise is added:

```text
delay_minutes = normal(delay_mean, 4)
delay_minutes = max(delay_minutes, 0)
delay_risk = 1 if delay_minutes >= 15 else 0
```

The main effects are:

| Signal | Effect added to `delay_mean` |
| --- | ---: |
| rush hour | `+1` |
| weekend | `+1` |
| holiday | `+1` |
| `weather_condition = Rain` | `+12` |
| `weather_condition = Heavy Rain` | `+24` |
| `transport_type = bus` | `+7` |
| `transport_type = tram` | `+4` |
| `transport_type = ferry` | `-1` |
| `mode = express` | `-3` |
| `service_level = premium` | `-2` |
| `operator = KMB` | `+4` |
| `operator = CTB` | `+1` |
| `operator = HKKF` | `-1` |
| `transport_detail = airport` | `+8` |
| `transport_detail = night` | `+6` |
| `transport_detail = crossharbour` | `+9` |

Location effects are also added from:

- `origin_station`
- `destination_station`
- the district mapped from `origin_station`

The district effect is intentionally strong enough that rebuilding a reliable
`district` value from the cleaned station is useful for the benchmark.

This design was intentional. If only one field carried the target signal, the
workshop would collapse into a single-field cleaning exercise. The current
dataset makes several cleaning areas matter:

- station normalization
- district rebuilding
- weather and country normalization
- transport parsing
- irrelevant-row filtering

## 3. `encoded_transport` Generation

Transport information is generated as separate internal components first:

| Component | Example values |
| --- | --- |
| `transport_type` | `bus`, `tram`, `ferry` |
| `transport_detail` | `general`, `airport`, `night`, `crossharbour` |
| `mode` | `local`, `express` |
| `service_level` | `standard`, `premium` |
| `operator` | `KMB`, `CTB`, `HKKF` |

These components are then packed into one clean field:

```text
<transport_type[-detail]>_<mode>_<service_level>_<operator>
```

Examples:

```text
bus_local_standard_KMB
bus-airport_local_premium_CTB
ferry-crossharbour_express_standard_HKKF
```

If `transport_detail` is `general`, it is omitted from the clean string.

## 4. Why Messy Data Was Generated From Clean Data

The workshop uses a two-step approach:

1. Generate a coherent clean dataset.
2. Apply controlled corruption to create a messy dataset.

This gives two benefits:

- the messy data still has recoverable structure
- the benchmark can measure how much cleaning recovers the clean signal

The goal is not to create random noise. The goal is to create realistic,
recoverable data quality problems.

## 5. Corruption By Data Type

### Categorical Fields

Affected fields include:

- `origin_station`
- `destination_station`
- `district`
- `weather_condition`
- `country_code`
- `encoded_transport`
- `day_of_week`

Common corruption types:

| Corruption type | Example |
| --- | --- |
| Casing changes | `central station`, `WAN CHAI` |
| Aliases and abbreviations | `TST`, `MK`, `NP`, `Central Stn` |
| Typo-like values | `Admiraltyy`, `Mongkok` |
| Legacy/source-system codes | `stn_central`, `np_ferry`, `wx_r`, `hkg` |
| Wrong but valid-looking categories | district value belongs to the wrong station |
| Placeholder values | `Unknown`, `missing`, source-specific null tags |

### Composite String Fields

Main field:

- `encoded_transport`

Corruption types:

| Corruption type | Example |
| --- | --- |
| Delimiter changes | `bus-airport|local|standard|KMB` |
| Wrappers | `svc:bus-airport_local_standard_KMB`, `meta[...]`, `legacy[...]` |
| Token reordering | mode and service level appear in the wrong position |
| Missing tokens | operator or service information omitted |
| Aliases | `CityBus`, `K.M.B.`, `prem`, `exp`, `crossharb` |
| Key-value formats | `operator=KMB;service=standard;mode=local;type=bus-airport` |
| Comment tails | `bus-airport_local_standard_KMB(note=late)` |

This field is intentionally challenging because it teaches candidates that one
fixed split or one rigid regex may not be enough.

### Numeric Fields

Warm-up fields:

- `fare_hkd`
- `distance_km`
- `scheduled_duration_min`

These are not part of the official benchmark input, but they are useful for
early cleaning practice.

Corruption types:

| Corruption type | Example |
| --- | --- |
| Unit text | `12.4 km`, `27.5 HKD`, `35 min` |
| Prefix text | `dist=12.4`, `fare=27.5`, `dur=35` |
| Approximate values | `about 12.4`, `~27.5` |
| Ranges | `12.4-13.6`, `35-43 min` |
| Time formats | `00:35:00`, `0.6 hrs` |
| Missing-like strings | `na-fare`, `n/a-dist`, `na-dur` |
| Outliers | unrealistically high or low fares, distances, or durations |
| Cross-field swaps | fare, distance, and duration values written into each other's fields |

## 6. Corruption By Problem Type

### 1. Formatting Inconsistency

Same value, different representation.

Examples:

- `Central Station`, `central station`, `Central Stn`
- `Rain`, `wx_r`, `heavy-rn`
- `HK`, `hkg`, `geo::852`

Cleaning lesson:

- normalize categories before modeling

### 2. Semantic Drift

The value is meaningful, but the source system uses a different convention.

Examples:

- station codes such as `stn_central`
- weather tags such as `wx.hr.critical`
- country tags such as `territory-hk`

Cleaning lesson:

- map source-system tags back to stable categories

### 3. Wrong Column / Schema Drift

Values may be valid, but appear in the wrong field.

Examples:

- `weather_condition` and `country_code` swapped
- `origin_station` and `destination_station` swapped
- `mode` and `service_level` swapped inside `encoded_transport`

Cleaning lesson:

- validate whether a value belongs to the expected column domain

### 4. Cross-Field Contradiction

Two fields disagree with each other.

Examples:

- `origin_station = Central Station` but `district = Sha Tin`
- weather-like value appears in `country_code`
- district does not match cleaned origin station

Cleaning lesson:

- use field relationships, not only single-column cleaning

### 5. Irrelevant Rows

Some records are not passenger transport trips.

Signals include:

- `survey_code = SYS`
- audit, maintenance, or staff movement tags
- stations such as `Depot`, `Workshop`, `Audit Hub`
- transport values such as `admin_move`, `test_run`, `maintenance_shift`

Cleaning lesson:

- row filtering is part of data cleaning

### 6. Duplicate And Conflicting Records

Some `record_id` values appear more than once.

There are two duplicate types:

| Type | Meaning |
| --- | --- |
| Exact duplicate | same row copied again |
| Conflicting duplicate | same `record_id`, but some fields disagree |

Cleaning lesson:

- duplicated IDs should be inspected before keeping or dropping rows

## 7. Why Layered Corruption Was Needed

Simple corruption was not enough. Early versions used issues such as casing
changes, missing values, and basic category variants, but the model still
performed too well.

The main reason is that messy-looking data is not automatically hard for a
model. If train and test contain the same dirty patterns, a tree-based model can
still learn those repeated patterns. Extra noisy columns may also be ignored,
and one strong field can dominate the prediction.

To lower ROC-AUC, the corruption had to damage the model's ranking ability, not
just make the table look untidy. The final design therefore uses layered
corruption that:

- attacks benchmark fields directly
- breaks shared category structure
- creates source-system shifts across record ranges
- puts valid values into the wrong columns
- introduces cross-field contradictions
- adds irrelevant rows with weak or random target relationships
- corrupts high-signal rows more heavily
- prevents one field, especially transport, from solving the task alone

The result is a messy dataset that performs worse before cleaning, but still has
recoverable signal for candidates who normalize categories, repair field
relationships, and remove out-of-scope rows.

## 8. Benchmark Result Shape

The current extracted benchmark uses these cleaned input fields:

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

Recent benchmark shape on the 10,000-row production-style data:

| Dataset state | ROC-AUC |
| --- | ---: |
| Clean reference | `0.9694` |
| Raw messy | `0.5991` |
| Messy after starter full cleaning | `0.6933` |

The benchmark also shows that different field groups contribute differently:

| Perfect-fix group | ROC-AUC |
| --- | ---: |
| Restore stations only | `0.8146` |
| Restore district only | `0.8154` |
| Restore transport components only | `0.5743` |
| Restore weather/country only | `0.6909` |

The key point for the talk:

```text
The dataset was not made messy just for appearance. The corruption was designed
to break model signal in realistic ways, then reward candidates who recover
stable categories, correct field relationships, and remove out-of-scope rows.
```

## 9. Talk Summary

The workshop dataset generation follows this structure:

1. Generate a clean, internally consistent synthetic transport dataset.
2. Generate delay risk from multiple meaningful signal groups.
3. Convert some useful transport structure into an encoded field.
4. Apply realistic corruption by data type and problem type.
5. Use model performance to check whether cleaning has a measurable impact.
6. Tune corruption until raw messy data performs poorly but remains recoverable.

This is why the workshop can demonstrate the value of data cleaning with model
metrics rather than only visual inspection.
