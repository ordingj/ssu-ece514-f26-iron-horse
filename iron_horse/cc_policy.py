"""Interpret Cc response fields without reading files or generating artifacts.

Use the shared matric decoder for framing, checksum, and sensor error checks.
Keep uncertain early units and truncated temperature fields explicit in the
returned quality flags. Phase timestamps mark observed response changes.
They do not establish calibration or a confirmed firmware unit setting.
Callers assign ``before_scale_change`` below ``FIRST_CHANGED``, then
``changed_scale_old_format`` below ``FIRST_STANDARD``, then ``standard_format``.
"""
import re
import pandas as pd
from .matric import (decode_response, FULL, EXPORTED, EXPORTED_ADDRESSED,
    PARTIAL, PARTIAL_ADDRESSED, PAIR, SDI, SHORT_V)

FIRST_CHANGED = pd.Timestamp('2026-03-21T14:52:24.985849Z')
FIRST_STANDARD = pd.Timestamp('2026-03-23T16:36:08.313361Z')


def fields(raw):
    """Extract literal numeric tokens from supported response shapes.

    Args:
        raw: Response to convert to text and match against known framing forms.

    Returns:
        First and second numeric tokens, or ``(None, None)`` if no shape matches.
        Tokens retain their signs, decimal points, and missing fractional digits.
        Shape matching does not check checksums, sentinels, or finite values.
    """
    for pattern in [FULL, EXPORTED, EXPORTED_ADDRESSED, PARTIAL, PARTIAL_ADDRESSED, SHORT_V]:
        m = pattern.fullmatch(str(raw).strip(' \n'))
        if m:
            return m['potential'], m['temperature']
    m = PAIR.fullmatch(str(raw).strip()) or SDI.fullmatch(str(raw).strip())
    return m.groups() if m else (None, None)


def correct(raw, phase):
    """Return raw fields, interpreted values, and explicit quality flags.

    Args:
        raw: Response accepted or rejected by the shared matric decoder.
        phase: Use ``before_scale_change`` for early Fahrenheit-like estimates.
            Other phase values use Celsius-like estimates for early responses.
            The phase does not change later-format interpretation.

    Returns:
        A dictionary with literal tokens, raw numbers, potential, strict and
        estimated temperatures, format and checksum status, and quality flags.
        Rejected responses retain any shape-matched raw fields. Their interpreted
        values stay ``None``.

        Accepted plain responses matching ``-?[0-9]+[.][0-9]{4} [0-9]+`` keep
        unknown potential units. One-character temperatures have no estimate.
        Other temperatures have phase-based estimates, but no strict Celsius value.

        Later formats retain reported potential. Signed or unsigned one-digit
        temperatures have no estimate. Other temperatures fill only the estimate
        field when their token ends with a point or lacks one. Remaining tokens
        fill both the strict and estimated Celsius fields.

    Examples:
        >>> correct('-577.4 20.', 'standard_format')['temperature_c'] is None
        True
        >>> correct('-577.4 20.', 'standard_format')['temperature_c_estimate']
        20.0
    """
    reading = decode_response(raw)
    first, second = fields(raw)
    r = {'first_field_text': first, 'second_field_text': second,
         'first_field_raw': float(first) if first is not None else None,
         'second_field_raw': float(second) if second is not None else None,
         'matric_potential_kpa': None, 'temperature_c': None,
         'temperature_c_estimate': None, 'temperature_unit_basis': 'unresolved',
         'temperature_quality': 'parse_rejected', 'potential_quality': 'parse_rejected',
         'response_format': reading.response_format if reading else 'rejected',
         'checksum_status': reading.checksum_status if reading else 'unavailable',
         'temperature_complete_numeric_field': False}
    if reading is None:
        return r
    early = bool(re.fullmatch(r'-?\d+\.\d{4} \d+', str(raw).strip()))
    if early:
        r['potential_quality'] = 'unknown_first_field_units'
        r['temperature_unit_basis'] = 'F_like_unconfirmed' if phase == 'before_scale_change' else 'C_like_unconfirmed'
        if len(second) == 1:
            r['temperature_quality'] = 'one_digit_prefix_unrecoverable'
        else:
            r['temperature_quality'] = 'unknown_unit_and_incomplete_response'
            value = float(second)
            r['temperature_c_estimate'] = (value - 32) * 5 / 9 if phase == 'before_scale_change' else value
        return r
    r['matric_potential_kpa'] = reading.potential_kpa
    r['potential_quality'] = 'reported_kpa_calibration_not_validated'
    r['temperature_unit_basis'] = 'C_supported_by_protocol_and_comparison'
    if re.fullmatch(r'[+-]?\d', second):
        r['temperature_quality'] = 'one_digit_prefix_unrecoverable'
    elif second.endswith('.') or '.' not in second:
        r['temperature_quality'] = 'numeric_prefix_fraction_missing'
        r['temperature_c_estimate'] = reading.temperature_c
    else:
        r['temperature_quality'] = 'numeric_field_complete'
        r['temperature_c'] = reading.temperature_c
        r['temperature_c_estimate'] = reading.temperature_c
        r['temperature_complete_numeric_field'] = True
    return r
