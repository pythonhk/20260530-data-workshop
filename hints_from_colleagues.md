## Disclosed Drift Ranges

The following `record_id` ranges can be disclosed to participants as hints.

| Drift batch      | Record range         | What happened                                                                                                            |
| ---------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `field_swap_a`   | `R03501` to `R04500` | Weather/country fields were swapped, and transport mode/service-level positions were swapped inside `encoded_transport`. |
| `field_swap_b`   | `R05501` to `R06500` | Origin and destination stations were swapped. District values may no longer match the true origin-side station.          |
| `tagging_switch` | `R07501` to `R08500` | Several fields were rewritten into legacy/source-system tags rather than simple swapped values.                          |

## `field_swap_a`

Affected fields:

- `weather_condition`
- `country_code`
- `encoded_transport`

Rules:

- `weather_condition` and `country_code` are swapped.
- Inside `encoded_transport`, `mode` and `service_level` are swapped.

## `field_swap_b`

Affected fields:

- `origin_station`
- `destination_station`
- `district`

Rules:

- `origin_station` and `destination_station` are swapped.
- `district` may become inconsistent with the intended origin station.

## `tagging_switch`

Affected fields:

- `origin_station`
- `destination_station`
- `weather_condition`
- `country_code`
- `encoded_transport`

Rules:

- This is not a simple two-column swap.
- Values were rewritten into legacy/source-system formats.
- Station names may appear as station codes or tagged values.
- Weather values may appear as legacy weather codes.
- Country codes may appear as alternate region tags.
- `encoded_transport` may appear in wrapped or source-specific formats.
