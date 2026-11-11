"""Parse two numeric matric fields and narrowly recognized METER frame trailers.

Original two-field and signed SDI forms stay unchanged. Historic v-terminated
pairs lack checksum bytes and are marked unavailable. Partial frames must pass
the retained legacy checksum and are marked CRC-unavailable. Complete
frames must match the manufacturer's legacy checksum and CRC6. The observed v
type is supported by the captured checksum-valid frame, not inferred from the
guide's k identifier. This parser does not validate field calibration.
"""
from dataclasses import dataclass
import math
import re

NUMBER = r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
SIGNED = rf'[+-]{NUMBER}'
PAIR = re.compile(rf'([+-]?{NUMBER})\s+([+-]?{NUMBER})')
SDI = re.compile(rf'[0-9A-Za-z]({SIGNED})({SIGNED})')
FIELDS = rf'(?P<potential>[+-]?{NUMBER}) (?P<temperature>[+-]?{NUMBER})'
METADATA = r'(?P<type>[kv])(?P<legacy>[\x20-\x5f])(?P<crc>[\x30-\x6f])'
FULL = re.compile(rf'(?:[0-9A-Za-z])?\t{FIELDS}\r{METADATA}')
EXPORTED = re.compile(rf'(?:[0-9A-Za-z](?=[+-]))?{FIELDS}{METADATA}')
EXPORTED_ADDRESSED = re.compile(rf'[0-9A-Za-z]{FIELDS}{METADATA}')
PARTIAL = re.compile(rf'{FIELDS}(?P<type>v)(?P<legacy>[\x20-\x5f])')
PARTIAL_ADDRESSED = re.compile(rf'[0-9A-Za-z]{FIELDS}(?P<type>v)(?P<legacy>[\x20-\x5f])')
SHORT_V = re.compile(rf'(?:[0-9A-Za-z](?=[+-]))?{FIELDS}v')


@dataclass(frozen=True)
class MatricReading:
    potential_kpa: float
    temperature_c: float
    response_format: str
    checksum_status: str
    sensor_type: str | None = None


def legacy_checksum(payload):
    """Checksum for TAB + two values + CR + sensor type, excluding address."""
    return chr(sum(payload.encode('ascii')) % 64 + 32)


def crc6(payload):
    """METER CRC-6-CDMA2000-A, printable offset 48; guide's example returns l."""
    crc = 0xfc
    for byte in payload.encode('ascii'):
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x9c if crc & 0x80 else crc << 1) & 0xff
    return chr((crc >> 2) + 48)


def reading(potential, temperature, response_format, checksum_status, sensor_type=None):
    potential, temperature = float(potential), float(temperature)
    if any(not math.isfinite(v) or v in {-9999., -9992.} for v in (potential, temperature)):
        return None
    return MatricReading(potential, temperature, response_format, checksum_status, sensor_type)


def decode_response(raw):
    # Preserve framing controls for complete DDI/XR frames before testing normalized exports.
    framed = str(raw).strip(' \n')
    for pattern in (FULL, EXPORTED, EXPORTED_ADDRESSED, PARTIAL, PARTIAL_ADDRESSED):
        match = pattern.fullmatch(framed)
        if match is None:
            continue
        fields = match.groupdict()
        payload = '\t' + fields['potential'] + ' ' + fields['temperature'] + '\r' + fields['type']
        if legacy_checksum(payload) != fields['legacy']:
            continue
        if 'crc' in fields:
            if crc6(payload + fields['legacy']) != fields['crc']:
                continue
            return reading(fields['potential'], fields['temperature'], 'meter_complete_frame',
                           'verified', fields['type'])
        return reading(fields['potential'], fields['temperature'], 'meter_partial_frame',
                       'legacy_verified_crc_unavailable', fields['type'])
    payload = str(raw).strip()
    match = PAIR.fullmatch(payload) or SDI.fullmatch(payload)
    if match is not None:
        return reading(*match.groups(), 'original_pair', 'not_present')
    match = SHORT_V.fullmatch(payload)
    if match is not None:
        return reading(match['potential'], match['temperature'], 'historical_v_terminated_pair',
                       'unavailable', 'v')
    return None


def decode_matric(raw):
    reading = decode_response(raw)
    return math.nan if reading is None else reading.potential_kpa
