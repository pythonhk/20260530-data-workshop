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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-input", required=True)
    parser.add_argument("--train-output", required=True)
    parser.add_argument("--test-input")
    parser.add_argument("--test-output")
    return parser.parse_args()


OPERATOR_ALIASES = {
    'CTB': 'CTB', 'citybus': 'CTB', 'CityBus': 'CTB', 'citybus_ctb': 'CTB',
    'ctb': 'CTB', 'cb': 'CTB',
    'KMB': 'KMB', 'K.M.B.': 'KMB', 'K.M.B': 'KMB', 'k.m.b': 'KMB',
    'Kowloon Motor Bus': 'KMB', 'kowloon': 'KMB', 'kmb': 'KMB',
    'HKKF': 'HKKF', 'HK Ferry': 'HKKF', 'Hong Kong Ferry': 'HKKF',
    'hkkf': 'HKKF', 'ferryhk': 'HKKF',
    'kmb_ctb': 'KMB',
}
TRANSPORT_TYPES = {'bus', 'tram', 'ferry'}
TRANSPORT_DETAILS = {
    'local', 'express', 'airport', 'night', 'crossharbour',
    'cross-harbour', 'crossharb', 'xhbr', 'XHBR',
}
SERVICE_LEVELS = {'standard', 'premium', 'std', 'prem', 'exp', 'express'}
MODES = {'local', 'express', 'exp', 'standard', 'premium', 'prem'}

def normalize_operator(op: str) -> str:
    op = op.strip()
    for alias, canonical in OPERATOR_ALIASES.items():
        if op.lower() == alias.lower():
            return canonical
    return op

KNOWN_TOKENS = {
    'bus': ('type', 'bus'), 'tram': ('type', 'tram'), 'ferry': ('type', 'ferry'),
    'local': ('detail', 'local'), 'loc': ('detail', 'local'),
    'express': ('detail', 'express'), 'exp': ('detail', 'express'),
    'airport': ('detail', 'airport'), 'apt': ('detail', 'airport'),
    'night': ('detail', 'night'), 'ngt': ('detail', 'night'),
    'crossharbour': ('detail', 'crossharbour'), 'crossharb': ('detail', 'crossharbour'),
    'cross-harbour': ('detail', 'crossharbour'), 'xhbr': ('detail', 'xhbr'),
    'standard': ('service', 'standard'), 'std': ('service', 'standard'),
    'premium': ('service', 'premium'), 'prem': ('service', 'premium'),
    'MISS': ('ignore', None),
}

OPERATOR_TOKENS = {'ctb', 'kmb', 'hkkf', 'citybus', 'cb', 'kmb_ctb', 'citybus_ctb', 'ferryhk'}

MULTI_WORD_OPERATORS = [
    ('kowloon motor bus', 'KMB'), ('kowloonmotor bus', 'KMB'),
    ('hong kong ferry', 'HKKF'), ('hongkong ferry', 'HKKF'),
    ('hk ferry', 'HKKF'),
]


def _match_multi_word_op(tokens: list[str], start: int) -> tuple[str | None, int]:
    """Check if tokens starting at start form a multi-word operator."""
    phrase = ' '.join(t.lower() for t in tokens[start:])
    for op_phrase, canonical in MULTI_WORD_OPERATORS:
        if phrase.startswith(op_phrase):
            n_words = len(op_phrase.split())
            return canonical, start + n_words
    # Also try single-word operator match
    if start < len(tokens):
        cat, val = _categorize_token(tokens[start])
        if val and cat == 'operator':
            return val, start + 1
        tl = tokens[start].lower().strip('-')
        if tl in OPERATOR_TOKENS:
            return normalize_operator(tl), start + 1
    return None, start


def _categorize_token(tok: str) -> tuple[str, str | None]:
    tl = tok.lower().strip('-')
    cat = KNOWN_TOKENS.get(tl)
    if cat:
        return cat
    op = normalize_operator(tok)
    if op != tok:
        return 'operator', op
    if tl in OPERATOR_TOKENS:
        return 'operator', normalize_operator(tl)
    if 'MISS' in tl:
        return 'ignore', None
    return None, None


def _parse_parts(tokens: list[str]) -> dict:
    result = {'transport_type': None, 'transport_detail': None,
              'mode': None, 'service_level': None, 'operator': None}

    # Try to handle multi-word operators by scanning from right
    op_val = None
    op_consumed = 0
    for i in range(len(tokens) - 1, -1, -1):
        op_candidate, next_idx = _match_multi_word_op(tokens, i)
        if op_candidate:
            op_val = op_candidate
            op_consumed = len(tokens) - i
            break

    type_v = detail_v = mode_v = service_v = None
    remaining = tokens[:len(tokens) - op_consumed] if op_consumed else list(tokens)

    # Categorize remaining tokens
    for p in remaining:
        cat, val = _categorize_token(p)
        if cat == 'type':
            type_v = val
        elif cat == 'detail':
            detail_v = val
        elif cat == 'service':
            service_v = val
        elif cat == 'mode':
            mode_v = val

    # If multiple detail tokens, first is transport_detail, last is mode
    detail_tokens = [t for t in remaining if _categorize_token(t)[0] == 'detail']
    if len(detail_tokens) >= 2:
        detail_v = _categorize_token(detail_tokens[0])[1]
        mode_v = _categorize_token(detail_tokens[-1])[1]
    elif detail_tokens:
        dv = _categorize_token(detail_tokens[0])[1]
        detail_v = dv
        if mode_v is None:
            mode_v = dv

    # Service from remaining
    if service_v is None:
        for p in remaining:
            if p.lower() in {'standard', 'premium', 'std', 'prem'}:
                service_v = p.lower()
                break

    # If only 3 remaining tokens and unknown middle, try positional heuristics
    unk = [p for p in remaining if _categorize_token(p)[0] is None]
    if type_v and op_val and len(remaining) == 2:
        # type + one other → that other could be detail/mode
        if detail_v is None and mode_v is None:
            detail_v = remaining[1].lower()
            mode_v = remaining[1].lower()
    elif type_v and len(remaining) >= 3:
        # positional: [type] [detail/mode] [service] ...
        for idx, p in enumerate(remaining):
            if idx == 1 and detail_v is None and mode_v is None:
                detail_v = p.lower()
                mode_v = p.lower()
            elif idx >= 1 and service_v is None and p.lower() in {'standard', 'premium'}:
                service_v = p.lower()

    result['transport_type'] = type_v
    result['transport_detail'] = detail_v
    result['mode'] = mode_v or detail_v
    result['service_level'] = service_v
    result['operator'] = op_val

    # If operator still missing, try last of remaining
    if result['operator'] is None and remaining:
        last = remaining[-1]
        cap, val = _categorize_token(last)
        if val and cap == 'operator':
            result['operator'] = val
        elif re.match(r'^[A-Za-z. ()/]+$', last):
            result['operator'] = normalize_operator(last)

    return result


def _preprocess(val: str) -> str:
    val = re.sub(r';backup=[^;]*', '', val)
    val = re.sub(r':v\d+', '', val)
    val = re.sub(r'(?:;tag=\w+|_tag=\w+|&tag=\w+)', '', val)
    val = val.replace('%20', ' ').replace('%2520', ' ')
    val = val.strip()
    if not val:
        return ''

    # Special single-word values
    if val.lower() in {'staff_shuttle', 'maintenance_shift', 'admin_move', 'test_run'}:
        return val.lower()

    # Bracket format - only if 2+ simple bracket groups
    m_bracket = re.findall(r'\[([A-Za-z0-9. /_-]+)\]', val)
    if len(m_bracket) >= 2:
        return ' '.join(m_bracket)

    # Strip legacy[...] wrapper and extract content
    m_legacy = re.search(r'\blegacy\[([^\]]+)\]', val)
    if m_legacy:
        val = m_legacy.group(1)

    # Handle vendor(kind=...,mode=...,tier=...,op=...) - extract parenthesized content
    m_vendor = re.search(r'vendor\s*\(([^)]+)\)', val, re.I)
    if m_vendor:
        val = m_vendor.group(1)

    # Strip remaining parenthetical suffixes (src=endcap)(batch=L2)
    val = re.sub(r'\([^)]*\)', '', val)

    # Strip UNK:: prefix
    val = re.sub(r'\bUNK::', '', val)

    # Strip meta[N]: or meta[N]_
    val = re.sub(r'\bmeta\d+[:_]', '', val)

    # Strip meta[route=N;value=...;flag=X] patterns
    val = re.sub(r'\bmeta\[route=\d+;value=', '', val)
    val = re.sub(r';flag=\w+\]', '', val)

    # Strip any remaining ] after extracting content
    val = re.sub(r'\]\s*$', '', val)

    # Extract bracket content: [tram][run=loc][tier=std] -> tram;run=loc;tier=std
    m_bracket = re.findall(r'\[([^\[\]]+)\]', val)
    if m_bracket:
        val = ';'.join(m_bracket)

    # Replace :: with spaces (colon-separated format)
    val = val.replace('::', ' ')

    # Split dots between lowercase letters (compound tokens like bus.loc.std.kowloon)
    val = re.sub(r'(?<=[a-z])\.(?=[a-z])', ' ', val)

    # Normalize commas to semicolons for key=value parsing
    val = val.replace(',', ';')

    # Strip op=, svc=, op:, svc: prefixes (including nested)
    while re.match(r'^(?:op[=:]|svc[=:])', val):
        val = re.sub(r'^(?:op[=:]|svc[=:])', '', val)

    # Strip duplicated suffix (_op=... or _ferry etc)
    val = re.sub(r'_(?:op|svc|meta)[=:].*', '', val)

    return val.strip()


def _to_tokens(val: str) -> list[str]:
    val = val.replace('__', ' ').replace('|', ' ').replace('/', ' ')
    val = val.replace(';', ' ').replace(',', ' ')
    val = val.replace('_', ' ')
    val = re.sub(r'(?<=[a-z])-(?=[a-z])', ' ', val)
    val = re.sub(r'[^A-Za-z0-9. _-]+', ' ', val)
    val = re.sub(r'\s+', ' ', val).strip()

    tokens = []
    for t in val.split():
        t = t.strip('-.').strip()
        if not t:
            continue
        tokens.append(t)
    return tokens


def _split_concatenated(tokens: list[str]) -> list[str]:
    """Try to split tokens that are concatenated without separators."""
    result = []
    for token in tokens:
        tl = token.lower()
        if tl in {'staff_shuttle', 'maintenance_shift', 'admin_move', 'test_run'}:
            result.append(token)
            continue
        if _categorize_token(token)[0] is not None:
            result.append(token)
            continue
        if len(token) <= 4:
            result.append(token)
            continue
        # Try left-to-right greedy matching
        sub_tokens = []
        remaining = tl
        while remaining:
            matched = False
            for end in range(len(remaining), 0, -1):
                prefix = remaining[:end]
                cat = KNOWN_TOKENS.get(prefix)
                if cat or prefix in OPERATOR_TOKENS:
                    sub_tokens.append(remaining[:end])
                    remaining = remaining[end:]
                    matched = True
                    break
            if not matched:
                sub_tokens.append(remaining)
                break
        result.extend(sub_tokens)
    return result


def _dedupe_consecutive(tokens: list[str]) -> list[str]:
    result = []
    for t in tokens:
        if result and t.lower() == result[-1].lower():
            continue
        result.append(t)
    return result


def parse_encoded_transport(val: str) -> dict:
    result = {
        'transport_type': None, 'transport_detail': None,
        'mode': None, 'service_level': None, 'operator': None,
    }
    if pd.isna(val) or not val:
        return result
    cleaned = _preprocess(str(val))
    if not cleaned:
        return result

    specials = {'staff_shuttle', 'maintenance_shift', 'admin_move', 'test_run'}
    if cleaned.lower() in specials:
        result['transport_type'] = cleaned.lower()
        result['operator'] = cleaned.lower()
        return result

    # Try structured key=value formats
    pairs = re.findall(r'(\w+)\s*=\s*([^;|&,]+)', cleaned)
    if pairs:
        d = dict(pairs)
        kv_keys = [k.lower() for k in d.keys()]
        if any(k in kv_keys for k in ('type', 'operator', 'op', 'svc', 'tier', 'service', 'mode', 'kind', 'run')):
            # Populate transport_detail from run/mode if available
            run_val = d.get('run', '').lower()
            if run_val and run_val not in ('?', '', 'missing', 'loc', 'exp'):
                det_cat = KNOWN_TOKENS.get(run_val)
                if det_cat and det_cat[0] == 'detail':
                    result['transport_detail'] = det_cat[1]
                elif result['transport_detail'] is None:
                    result['transport_detail'] = run_val

            if 'operator' in d:
                result['operator'] = normalize_operator(d['operator']) if d['operator'].lower() not in ('unknown', '?', '') else None
            elif 'op' in d:
                result['operator'] = normalize_operator(d['op']) if d['op'].lower() not in ('unknown', '?', '') else None
            svc_raw = d.get('service', d.get('tier', ''))
            svc_val = svc_raw.lower() if svc_raw.lower() not in ('?', '', 'missing') else ''
            svc_cat = KNOWN_TOKENS.get(svc_val)
            if svc_cat and svc_cat[0] == 'service':
                svc_val = svc_cat[1]
            result['service_level'] = svc_val
            mode_raw = d.get('mode', d.get('run', ''))
            mode_val = mode_raw.lower() if mode_raw.lower() not in ('?', '', 'missing') else ''
            if mode_val in ('loc',):
                mode_val = 'local'
            elif mode_val in ('exp',):
                mode_val = 'express'
            det_cat = KNOWN_TOKENS.get(mode_val)
            if det_cat and det_cat[0] == 'detail':
                mode_val = det_cat[1]
            result['mode'] = mode_val
            # For kind=, prefer first occurrence (not 'alt' placeholder)
            raw_type = d.get('type', d.get('svc', ''))
            if not raw_type or raw_type in ('', '?'):
                raw_type = d.get('kind', '')
            if raw_type in ('alt', ''):
                # Try to find first kind value that's not 'alt' from original pairs
                for k, v in pairs:
                    if k.lower() == 'kind' and v not in ('alt', ''):
                        raw_type = v
                        break
            if raw_type and raw_type not in ('alt', '', '?'):
                tp = raw_type.split('-', 1)
                result['transport_type'] = tp[0].lower()
                if len(tp) > 1:
                    result['transport_detail'] = tp[1].lower()
            # If no type from kv pairs, check non-kv tokens in cleaned
            if result['transport_type'] is None:
                non_kv = re.sub(r'\w+\s*=\s*[^;|&]+', '', cleaned)
                non_kv_tokens = _to_tokens(non_kv)
                for tok in non_kv_tokens:
                    cat, val = _categorize_token(tok)
                    if cat == 'type':
                        result['transport_type'] = val
                        break
                    if cat == 'detail' and result['transport_detail'] is None:
                        result['transport_detail'] = val
                        if result['mode'] is None:
                            result['mode'] = val
            return result

    tokens = _to_tokens(cleaned)

    # Try to split concatenated tokens
    if len(tokens) <= 3:
        split_tokens = _split_concatenated(tokens)
        if len(split_tokens) > len(tokens):
            tokens = split_tokens

    # Handle multi-word operators by re-parsing remaining
    op_val = None
    for i in range(len(tokens) - 1, -1, -1):
        op_candidate, _ = _match_multi_word_op(tokens, i)
        if op_candidate:
            op_val = op_candidate
            break

    # If op found from right, remove those tokens
    op_consumed = 0
    if op_val:
        for i in range(len(tokens) - 1, -1, -1):
            op_candidate, _ = _match_multi_word_op(tokens, i)
            if op_candidate:
                op_consumed = len(tokens) - i
                break

    if op_consumed:
        handlers = tokens[:len(tokens) - op_consumed]
    else:
        handlers = list(tokens)

    result['operator'] = op_val

    # Now classify handler tokens
    type_v = detail_v = mode_v = service_v = None
    for p in handlers:
        cat, val_cat = _categorize_token(p)
        if cat == 'type' and type_v is None:
            type_v = val_cat
        elif cat == 'detail':
            if detail_v is None:
                detail_v = val_cat
            else:
                mode_v = val_cat
        elif cat == 'mode':
            mode_v = val_cat
        elif cat == 'service':
            service_v = val_cat

    # Positional heuristics for ambiguous cases
    if len(handlers) >= 2 and type_v is None:
        first_cat = _categorize_token(handlers[0])
        if first_cat[0] is None:
            type_v = handlers[0].lower()

    if type_v and op_val is None and handlers:
        last = handlers[-1]
        cat_op = _categorize_token(last)
        if cat_op[0] == 'operator':
            result['operator'] = cat_op[1]
        elif result['operator'] is None:
            result['operator'] = normalize_operator(last)

    if service_v is None:
        for p in handlers:
            if p.lower() in {'standard', 'premium', 'std', 'prem'}:
                service_v = p.lower()
                break

    if detail_v is None and mode_v is None:
        for p in handlers:
            if p.lower() in {'local', 'express', 'airport', 'night',
                             'crossharbour', 'crossharb', 'xhbr'}:
                detail_v = p.lower()
                mode_v = p.lower()
                break

    result['transport_type'] = type_v
    result['transport_detail'] = detail_v
    result['mode'] = mode_v or detail_v
    result['service_level'] = service_v

    if result['operator'] is None:
        for t in reversed(tokens):
            if normalize_operator(t) != t:
                result['operator'] = normalize_operator(t)
                break

    return result


def _tokenize(val: str) -> list[str]:
    """Convert a transport encoding string into a list of meaningful tokens."""
    val = re.sub(r';backup=[^;]*', '', val)
    val = re.sub(r'(?:^|[;|])backup=[^;]*', '', val)
    val = re.sub(r':v\d+', '', val)
    val = re.sub(r'\([^)]*\)', '', val)
    val = re.sub(r'(?:;tag=\w+|_tag=\w+)', '', val)
    val = val.replace('%20', ' ').replace('%2520', ' ')
    val = val.strip()

    # Special single-word values
    if val.lower() in {'staff_shuttle', 'maintenance_shift', 'admin_move', 'test_run'}:
        return [val.lower()]

    # Bracket format: [bus][local][standard][K.M.B.]
    m_bracket = re.findall(r'\[([^\]]+)\]', val)
    if m_bracket:
        return m_bracket

    # Strip structured prefixes
    for prefix in ['svc:', 'svc=', 'op=', 'op:', 'svc:svc:']:
        if val.startswith(prefix):
            val = val[len(prefix):]
            break

    # Normalize all separators to space
    val = re.sub(r'[|;/]', ' ', val)
    val = val.replace('__', ' ').replace('_', ' ')
    # Also replace hyphens with spaces (but watch for hyphenated operator names like K.M.B.)
    val = re.sub(r'(?<![A-Za-z])-(?![A-Za-z.])', ' ', val)
    val = re.sub(r'(?<=[a-z0-9])-(?=[a-z])', ' ', val)

    tokens = []
    for segment in val.split():
        s = segment.strip('-').strip()
        if not s:
            continue
        # Further split on remaining hyphens
        for sub in re.split(r'-+', s):
            sub = sub.strip()
            if not sub:
                continue
            tokens.append(sub)
    return tokens


# Start input your code
def parse_fare(val):
    if pd.isna(val):
        return None
    val = str(val).strip()
    if val.lower() in ('missing', 'na-fare', 'na', ''):
        return None
    val = val.replace(',', '.')
    for p in ['HK$', 'HKD:', ' fare', ' HKD', 'fare=', 'fare=']:
        val = val.replace(p, '')
    val = val.lstrip('~').strip()
    if '-' in val:
        parts = val.split('-')
        if len(parts) == 2:
            try:
                lo, hi = float(parts[0].strip()), float(parts[1].strip())
                return (lo + hi) / 2
            except ValueError:
                return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_distance(val):
    if pd.isna(val):
        return None
    val = str(val).strip()
    if val.lower() in ('unknown', 'n/a-dist', 'n/a', ''):
        return None
    val = val.replace(',', '.')
    val = re.sub(r'\babout\b', '', val, flags=re.I).strip()
    val = re.sub(r'\bapprox\b', '', val, flags=re.I).strip()
    val = val.replace(' / route', '').replace('/route', '')
    val = val.replace('dist=', '')
    val = val.strip()
    m_match = re.match(r'^([\d.]+)\s*m$', val)
    if m_match:
        return float(m_match.group(1)) / 1000
    val = re.sub(r'\s*km$', '', val, flags=re.I).strip()
    if '-' in val and not val.startswith('-'):
        parts = val.split('-')
        if len(parts) == 2:
            try:
                lo, hi = float(parts[0].strip()), float(parts[1].strip())
                return (lo + hi) / 2
            except ValueError:
                return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_duration(val):
    if pd.isna(val):
        return None
    val = str(val).strip()
    if val.lower() in ('na-dur', 'na', ''):
        return None
    val = val.replace(',', '.')
    m = re.match(r'^(\d+):(\d+):(\d+)$', val)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return float(h * 60 + mn + s / 60)
    m = re.match(r'^([\d.]+)\s*hrs?$', val)
    if m:
        return float(m.group(1)) * 60
    for p in ['about ', 'm est', ' min', 'min ', 'dur=']:
        val = val.replace(p, '')
    val = re.sub(r'^T(\d+)$', r'\1', val)
    val = val.strip()
    val_clean = re.sub(r'\s*min\s*$', '', val)
    if '-' in val_clean and not val_clean.startswith('-'):
        parts = val_clean.split('-')
        if len(parts) == 2:
            try:
                lo, hi = float(parts[0].strip()), float(parts[1].strip())
                return (lo + hi) / 2
            except ValueError:
                return None
    try:
        return float(val_clean)
    except ValueError:
        return None


STATION_MAPPING = {
    'ADM': 'Admiralty', 'ADMIRALTY': 'Admiralty', 'AdmiraltyIRALTY': 'Admiralty', 'Admiraltyy': 'Admiralty', 'AdmiraltyStation': 'Admiralty',
    'adm': 'Admiralty', 'adm_xfer': 'Admiralty', 'admiralty': 'Admiralty', 'admiralty station': 'Admiralty', 'admiraltyy': 'Admiralty',
    'C': 'Central', 'CENTRAL': 'Central', 'Centralentral': 'Central', 'CentralTRAL': 'Central', 'CentralWB': 'Central',
    'CEN': 'Central', 'CENStation': 'Central', 'CENTRALSTATION': 'Central', 'CentralStation': 'Central', 'CentralStn': 'Central',
    'c station': 'Central', 'cen station': 'Central', 'central': 'Central', 'central station': 'Central', 'central stn': 'Central',
    'centralstation': 'Central', 'stn_central': 'Central',
    'cs': 'Central',
    'CAUSEWAY BAY': 'Causeway Bay', 'Causeway Bay': 'Causeway Bay', 'CAUSEWAYBAY': 'Causeway Bay',
    'CWB': 'Causeway Bay', 'CausewayBay': 'Causeway Bay', 'Causewaybay': 'Causeway Bay',
    'causeway bay': 'Causeway Bay', 'causewaybay': 'Causeway Bay', 'cwb': 'Causeway Bay', 'cwb_hub': 'Causeway Bay',
    'cb': 'Causeway Bay',
    'K Town': 'Kennedy Town', 'KENNEDY TOWN': 'Kennedy Town', 'KENNEDYTOWN': 'Kennedy Town',
    'KTown': 'Kennedy Town', 'Kennedy Tn': 'Kennedy Town', 'KennedyTn': 'Kennedy Town', 'KennedyTown': 'Kennedy Town',
    'k town': 'Kennedy Town', 'kennedy tn': 'Kennedy Town', 'kennedy town': 'Kennedy Town',
    'kennedytown': 'Kennedy Town', 'ktown_stop': 'Kennedy Town',
    'kt': 'Kennedy Town',
    'MK': 'Mong Kok', 'MONG KOK': 'Mong Kok', 'MONGKOK': 'Mong Kok', 'Mong interface': 'Mong Kok', 'Mongfile': 'Mong Kok', 'Mongkok': 'Mong Kok',
    'MongKok': 'Mong Kok', 'mk': 'Mong Kok', 'mk_hub': 'Mong Kok', 'mong kok': 'Mong Kok', 'mongkok': 'Mong Kok',
    'NORTH POINT': 'North Point', 'NORTHPOINT': 'North Point', 'NP': 'North Point',
    'North Pt': 'North Point', 'NorthPoint': 'North Point', 'NorthPt': 'North Point',
    'north point': 'North Point', 'north pt': 'North Point', 'northpoint': 'North Point', 'np': 'North Point', 'np_ferry': 'North Point',
    'S Tin': 'Sha Tin', 'SHA TIN': 'Sha Tin', 'SHATIN': 'Sha Tin', 'STin': 'Sha Tin', 'ShaTin': 'Sha Tin', 'Shatin': 'Sha Tin',
    's tin': 'Sha Tin', 'sha tin': 'Sha Tin', 'shatin': 'Sha Tin', 'shatin_term': 'Sha Tin',
    'st': 'Sha Tin',
    'TSIM SHA TSUI': 'Tsim Sha Tsui', 'TSIMSHATSUI': 'Tsim Sha Tsui',
    'TsimShaTsui': 'Tsim Sha Tsui', 'tsim sha tsui': 'Tsim Sha Tsui', 'tsimshatsui': 'Tsim Sha Tsui',
    'tst': 'Tsim Sha Tsui', 'TST': 'Tsim Sha Tsui',
    'tsim sha tsui east': 'Tsim Sha Tsui East', 'TsimShaTsuiEast': 'Tsim Sha Tsui East', 'tst_east': 'Tsim Sha Tsui East',
    'TSUEN WAN': 'Tsuen Wan', 'TSUENWAN': 'Tsuen Wan', 'TWN': 'Tsuen Wan',
    'TsuenWan': 'Tsuen Wan', 'Tswan': 'Tsuen Wan', 'tsuen wan': 'Tsuen Wan', 'tsuenwan': 'Tsuen Wan',
    'tsw_line': 'Tsuen Wan', 'tswan': 'Tsuen Wan', 'twn': 'Tsuen Wan',
    'tw': 'Tsuen Wan',
    'W Chai': 'Wan Chai', 'WAN CHAI': 'Wan Chai', 'WANCHAI': 'Wan Chai',
    'WChai': 'Wan Chai', 'WanChai': 'Wan Chai', 'Wanchai': 'Wan Chai',
    'wan chai': 'Wan Chai', 'wanchai': 'Wan Chai', 'wanchai_stop': 'Wan Chai', 'w chai': 'Wan Chai',
    'wc': 'Wan Chai',
}

COUNTRY_MAP = {
    'hkg': 'HK', 'geo::hkg': 'HK', '852': 'HK', 'territory-hk': 'HK',
    'geo::852': 'HK', 'hk-zone': 'HK', 'geo-hkg-v2': 'HK',
    'chn': 'CN', 'CHN': 'CN', 'mac': 'MO', 'MAC': 'MO',
    # Test-only codes
    'legacy-null': None, 'geo-miss': None, 'UNK': None, '??': None,
    'N/A-HK': 'HK', 'HK-L2': 'HK', 'HK-01': 'HK', 'HK-OPS': 'HK',
    '852-HK': 'HK', 'geo-852-v2': 'HK', 'geo-hk-zone-v2': 'HK',
    'legacy': None, 'geo::mac': 'MO', 'geo::na_region': None,
    'na_region': None, 'TST': None, 'INT': None, 'SYS': None,
    'geo-legacy-v2': None,
}

WEATHER_NORM = {
    'Sunny': 'Sunny', 'sunny': 'Sunny', 'SUNNY': 'Sunny',
    'Cloudy': 'Cloudy', 'cloudy': 'Cloudy', 'CLOUDY': 'Cloudy',
    'Rain': 'Rain', 'rain': 'Rain', 'RAIN': 'Rain',
    'Heavy Rain': 'Heavy Rain', 'heavy-rn': 'Heavy Rain',
    'HEAVY_RAIN': 'Heavy Rain', 'HeavyRain': 'Heavy Rain',
    'rain??': 'Rain', 'clr': 'Clear',
    # Test-only codes
    'WXS': 'Sunny', 'wx.sun.sig': 'Sunny', 'weather:clear_v2': 'Sunny',
    'wx=clear_ops': 'Sunny',
    'WXC': 'Cloudy', 'wx.cld.ops': 'Cloudy', 'cld-shift': 'Cloudy',
    'weather:cloud_v2': 'Cloudy', 'wx=cloud_ops': 'Cloudy',
    'WXR': 'Rain', 'weather:rain_v2': 'Rain', 'rn-v2': 'Rain',
    'wx=rain_ops': 'Rain', 'hrn-ops': 'Rain',
    'WXHR': 'Heavy Rain', 'wx.hr.critical': 'Heavy Rain',
    'wx=storm_ops': 'Heavy Rain', 'weather:storm_v2': 'Heavy Rain',
    'wx-s-v2': None,
}

COUNTRY_RAW = {'HK', 'CN', 'MO', '852', 'geo::hkg', 'hkg', 'hk-zone',
               'territory-hk', 'geo::852', 'geo-hkg-v2', 'chn', 'CHN', 'mac', 'MAC',
               'legacy-null', 'geo-miss', 'UNK', '??', 'N/A-HK', 'HK-L2', 'HK-01',
               'HK-OPS', '852-HK', 'geo-852-v2', 'geo-hk-zone-v2', 'legacy',
               'geo::mac', 'geo::na_region', 'na_region', 'TST', 'INT', 'SYS',
               'geo-legacy-v2'}
WEATHER_RAW = {'Sunny', 'sunny', 'SUNNY', 'Cloudy', 'cloudy', 'CLOUDY',
               'Rain', 'rain', 'RAIN', 'heavy-rn', 'HEAVY_RAIN', 'HeavyRain',
               'Heavy Rain', 'rain??', 'clr',
               'WXS', 'wx.sun.sig', 'weather:clear_v2', 'wx=clear_ops',
               'WXC', 'wx.cld.ops', 'cld-shift', 'weather:cloud_v2', 'wx=cloud_ops',
               'WXR', 'weather:rain_v2', 'rn-v2', 'wx=rain_ops', 'hrn-ops',
               'WXHR', 'wx.hr.critical', 'wx=storm_ops', 'weather:storm_v2',
               'wx-s-v2'}
SERVICE_VALS = {'Test', 'System', 'Audit', 'Unknown', 'TBD', 'legacy',
                'WX?', 'wx=miss', 'weather:null_v2', 'wx=legacy',
                'wx_unknown', 'weather:ops_v2', 'Audit Hub', 'Depot', 'Workshop'}
SURVEY_VALS = {'TST', 'INT', 'SYS', 'na_region'}
OPS_VALS = {'wx_s', 'wx.cld.ops', 'wx.rn.alert', 'wx.hr.critical', 'wx_c', 'wx_hr', 'wx_r'}


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Normalise stations
    STATION_PREFIXES = [
        'O:', 'D:', 'src::', 'dst::', 'src-', 'dst-', 'from=', 'to=',
        'node::', 'station::', 'orig=UNK|', 'dest=UNK|', 'orig|', 'dest|',
    ]
    STATION_SUFFIXES = ['|OPS', '_v2', '::l2']

    def _normalise_station(val, is_origin):
        if pd.isna(val):
            return val
        s = str(val).strip()
        if not s:
            return s

        for prefix in STATION_PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix):]
                break

        for suffix in STATION_SUFFIXES:
            if s.endswith(suffix):
                s = s[:-len(suffix)]
                break

        s = s.replace('%2520', ' ').replace('%20', ' ')

        parts = re.split(r':+', s)
        if len(parts) == 2 and parts[0] and parts[1]:
            code = parts[0] if is_origin else parts[1]
        elif len(parts) == 1:
            code = parts[0]
        else:
            code = s

        if '|' in code:
            code = code.split('|')[0]

        code = code.replace('.', '').replace('Station', '').replace('Stn', '').replace('STATION', '')
        code = re.sub(r'\s+', ' ', code).strip()

        # Try direct lookup, then with underscores, then with spaces
        for variant in [code, code.replace(' ', '_'), code.replace('_', ' ')]:
            for key, val in STATION_MAPPING.items():
                if key.lower() == variant.lower():
                    return val
        return code

    df['origin_station'] = df['origin_station'].apply(lambda v: _normalise_station(v, is_origin=True))
    df['destination_station'] = df['destination_station'].apply(lambda v: _normalise_station(v, is_origin=False))

    # Parse numeric columns
    if 'fare_hkd' in df.columns:
        df['fare_hkd'] = df['fare_hkd'].apply(parse_fare).astype(float)
    if 'distance_km' in df.columns:
        df['distance_km'] = df['distance_km'].apply(parse_distance).astype(float)
    if 'scheduled_duration_min' in df.columns:
        df['scheduled_duration_min'] = df['scheduled_duration_min'].apply(parse_duration).astype(float)

    # Normalise day_of_week
    df['day_of_week'] = df['day_of_week'].str.capitalize()

    # Normalise weather_condition
    df['weather_condition'] = df['weather_condition'].replace(WEATHER_NORM)

    # Normalise country_code
    country_normed = []
    for v in df['country_code']:
        if pd.isna(v):
            country_normed.append(v)
        else:
            s = str(v).strip()
            # Strip cc= prefix and |OPS suffix
            s = re.sub(r'^cc=', '', s)
            s = re.sub(r'\|OPS$', '', s)
            country_normed.append(COUNTRY_MAP.get(s, s))
    df['country_code'] = country_normed

    if 'encoded_transport' in df.columns:
        df['encoded_transport'] = df['encoded_transport'].fillna('')

    # Cross-column cleanup
    def classify(val):
        if pd.isna(val):
            return None, None
        if val in COUNTRY_RAW:
            return 'country_code', COUNTRY_MAP.get(val, val)
        if val in WEATHER_RAW:
            return 'weather_condition', WEATHER_NORM.get(val, val)
        if val in SERVICE_VALS:
            return 'service_note', val
        if val in SURVEY_VALS:
            return 'survey_code', val
        if val in OPS_VALS:
            return 'ops_comment_code', val
        return 'keep', val

    import numpy as np
    new_wc = []
    new_cc = []
    new_sn = []
    new_sc = []
    new_ops = []

    for _, row in df.iterrows():
        wc_dest, wc_clean = classify(row['weather_condition'])
        cc_dest, cc_clean = classify(row['country_code'])

        cur_wc = np.nan
        cur_cc = np.nan
        cur_sn = row['service_note']
        cur_sc = row['survey_code']
        cur_ops = row['ops_comment_code']

        for src_col, dest, clean_val in [
            ('weather_condition', wc_dest, wc_clean),
            ('country_code', cc_dest, cc_clean),
        ]:
            if dest == 'weather_condition':
                cur_wc = clean_val
            elif dest == 'country_code':
                cur_cc = clean_val
            elif dest == 'service_note':
                cur_sn = clean_val
            elif dest == 'survey_code':
                cur_sc = clean_val
            elif dest == 'ops_comment_code':
                cur_ops = f"{cur_ops} | {clean_val}" if pd.notna(cur_ops) else clean_val
            elif dest == 'keep':
                if src_col == 'weather_condition':
                    cur_wc = clean_val
                else:
                    cur_cc = clean_val

        new_wc.append(cur_wc)
        new_cc.append(cur_cc)
        new_sn.append(cur_sn)
        new_sc.append(cur_sc)
        new_ops.append(cur_ops)

    df['weather_condition'] = new_wc
    df['country_code'] = new_cc
    df['service_note'] = new_sn
    df['survey_code'] = new_sc
    df['ops_comment_code'] = new_ops

    # Parse encoded_transport into feature columns
    transport_parsed = df['encoded_transport'].apply(parse_encoded_transport)
    for col in ['transport_type', 'transport_detail', 'mode', 'service_level', 'operator']:
        df[col] = transport_parsed.apply(lambda x, c=col: x.get(c))

    # Normalise district - map zone codes to canonical names, null non-real
    DISTRICT_ZONE_MAP = {
        'CW': 'Central and Western', 'cw_core': 'Central and Western',
        'D-CW': 'Central and Western', 'LEG-CW': 'Central and Western',
        'EH': 'Eastern', 'east_harbour': 'Eastern',
        'D-EH': 'Eastern', 'LEG-EH': 'Eastern',
        'ST': 'Sha Tin', 'shatin_new': 'Sha Tin',
        'D-ST': 'Sha Tin', 'LEG-ST': 'Sha Tin',
        'TW': 'Tsuen Wan', 'tsw_sector': 'Tsuen Wan',
        'D-TW': 'Tsuen Wan', 'LEG-TW': 'Tsuen Wan',
        'WC': 'Wan Chai', 'wchai_zone': 'Wan Chai',
        'D-WC': 'Wan Chai', 'LEG-WC': 'Wan Chai',
        'YTM': 'Yau Tsim Mong', 'ytm_cluster': 'Yau Tsim Mong',
        'D-YTM': 'Yau Tsim Mong', 'LEG-YTM': 'Yau Tsim Mong',
    }
    NON_REAL_DISTRICTS = {
        'Audit', 'Operations', 'Internal',
        'Legacy', 'Legacy-Null', '??',
        'hold::mismatch', 'zone=UNK|OPS',
        'district::unknown', 'district::legacy',
    }
    REAL_DISTRICT_NAMES = {'Central and Western', 'Sha Tin', 'Yau Tsim Mong',
                           'Wan Chai', 'Eastern', 'Tsuen Wan'}

    def _clean_district(val):
        if pd.isna(val):
            return None
        s = str(val).strip()
        s = re.sub(r'^(?:zone|region|hold)::', '', s)
        s = re.sub(r'^zone=', '', s)
        s = re.sub(r'^district::', '', s)
        s = re.sub(r'\|OPS$', '', s)
        if s in DISTRICT_ZONE_MAP:
            return DISTRICT_ZONE_MAP[s]
        if s in REAL_DISTRICT_NAMES:
            return s
        if s in NON_REAL_DISTRICTS:
            return None
        return None

    df['district'] = df['district'].apply(_clean_district)

    # Normalise route_label_variant
    df['route_label_variant'] = (
        df['route_label_variant']
        .str.strip()
        .str.upper()
        .str.replace(r'[ _-]+', '-', regex=True)
    )

    # Fill NaN scheduled_duration_min with median by route
    if 'scheduled_duration_min' in df.columns:
        route_median = df.groupby('route_label_variant')['scheduled_duration_min'].transform('median')
        df['scheduled_duration_min'] = df['scheduled_duration_min'].fillna(route_median)

    # Fill NaN fare_hkd with fare_hkd_rounded
    if 'fare_hkd' in df.columns and 'fare_hkd_rounded' in df.columns:
        df['fare_hkd'] = df['fare_hkd'].fillna(df['fare_hkd_rounded'])

    # Fill NaN distance_km with distance_m/1000
    if 'distance_km' in df.columns and 'distance_m' in df.columns:
        df['distance_km'] = df['distance_km'].fillna(df['distance_m'] / 1000.0)

    # Fill NaN country_code with HK
    if 'country_code' in df.columns:
        df['country_code'] = df['country_code'].fillna('HK')

    # Deduplicate (test input also has duplicate record_ids)
    df = df.drop_duplicates(subset='record_id', keep='first')

    # Impute outliers and zero values with column mean (same for train and test)
    if 'fare_hkd' in df.columns:
        good = (df['fare_hkd'] != 9000) & (df['fare_hkd'] != 0) & df['fare_hkd'].notna()
        if good.any():
            mean_val = df.loc[good, 'fare_hkd'].mean()
            mask = (df['fare_hkd'] == 9000) | (df['fare_hkd'] == 0)
            df.loc[mask, 'fare_hkd'] = mean_val
    if 'distance_km' in df.columns:
        good = (df['distance_km'] <= 1000) & df['distance_km'].notna()
        if good.any():
            mean_val = df.loc[good, 'distance_km'].mean()
            df.loc[df['distance_km'] > 1000, 'distance_km'] = mean_val
    if 'scheduled_duration_min' in df.columns:
        good = (df['scheduled_duration_min'] <= 300) & (df['scheduled_duration_min'] != 0) & df['scheduled_duration_min'].notna()
        if good.any():
            mean_val = df.loc[good, 'scheduled_duration_min'].mean()
            mask = (df['scheduled_duration_min'] > 300) | (df['scheduled_duration_min'] == 0)
            df.loc[mask, 'scheduled_duration_min'] = mean_val

    return df
# End of your code


def main() -> None:
    args = parse_args()
    train = pd.read_csv(args.train_input)
    # Start input your code
    cleaned_train = _clean_frame(train)
    #
    # End of your code
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
