import re
from typing import Tuple, Optional

# Conversion factors to target units
# Pressure: target is psi
PRESSURE_FACTORS = {
    "psi": 1.0,
    "bar": 14.5037738,
    "kpa": 0.145037738,
    "mpa": 145.037738,
    "atm": 14.6959488,
}

# Permeability: target is mD
PERM_FACTORS = {
    "md": 1.0,
    "d": 1000.0,
}

# Viscosity: target is cp
VISCOSITY_FACTORS = {
    "cp": 1.0,
    "pas": 1000.0,
    "pa.s": 1000.0,
    "mpas": 1.0,
    "mpa.s": 1.0,
}

# Temperature: target is F
TEMPERATURE_UNITS = frozenset({"c", "celsius", "k", "kelvin", "f", "fahrenheit"})

# Units each property kind can actually convert. An unknown unit is an error,
# never a silent 1.0 factor: the caller labels converted columns
# "[UNITS NORMALIZED]" in the ground-truth the model reads.
KNOWN_UNITS = {
    "pressure": frozenset(PRESSURE_FACTORS),
    "temperature": TEMPERATURE_UNITS,
    "permeability": frozenset(PERM_FACTORS),
    "viscosity": frozenset(VISCOSITY_FACTORS),
}

def clean_unit_name(name: str) -> str:
    # Normalize unit name: lowercase, strip symbols/spaces
    u = name.lower().strip()
    u = u.replace("°", "").replace("deg", "")
    return u.strip()

def _factor(table: dict, from_unit: str, prop: str) -> float:
    u = clean_unit_name(from_unit)
    if u not in table:
        raise ValueError(f"unknown {prop} unit {from_unit!r} (known: {sorted(table)})")
    return table[u]

def convert_pressure(val: float, from_unit: str) -> float:
    return val * _factor(PRESSURE_FACTORS, from_unit, "pressure")

def convert_temperature(val: float, from_unit: str) -> float:
    u = clean_unit_name(from_unit)
    if u in ("c", "celsius"):
        return val * 9.0 / 5.0 + 32.0
    elif u in ("k", "kelvin"):
        return (val - 273.15) * 9.0 / 5.0 + 32.0
    elif u in ("f", "fahrenheit"):
        return val
    raise ValueError(f"unknown temperature unit {from_unit!r} (known: {sorted(TEMPERATURE_UNITS)})")

def convert_permeability(val: float, from_unit: str) -> float:
    return val * _factor(PERM_FACTORS, from_unit, "permeability")

def convert_viscosity(val: float, from_unit: str) -> float:
    return val * _factor(VISCOSITY_FACTORS, from_unit, "viscosity")

def detect_unit(header: str) -> Optional[Tuple[str, str]]:
    """
    Detects petrophysical property kind and unit from a column header or text.
    Returns: (property_type, unit_symbol) or None
    e.g. "Pressure (bar)" -> ("pressure", "bar")
         "T (C)" -> ("temperature", "C")
    """
    # Regex to find unit symbol in parentheses or brackets
    m = re.search(r'\b(pressure|temp|temperature|permeability|perm|viscosity|p|t|k)\b.*?\(([^)]+)\)', header, re.IGNORECASE)
    if not m:
        m = re.search(r'\b(pressure|temp|temperature|permeability|perm|viscosity|p|t|k)\b.*?\[([^\]]+)\]', header, re.IGNORECASE)
    if m:
        prop = m.group(1).lower()
        unit = m.group(2).strip()

        # Classify property kind
        if prop in ("p", "pressure"):
            kind = "pressure"
        elif prop in ("t", "temp", "temperature"):
            kind = "temperature"
        elif prop in ("k", "perm", "permeability"):
            kind = "permeability"
        else:
            kind = "viscosity"
        # Only a unit we can convert is a detection: the single-letter p/t/k
        # pattern also matches 't (min)' / 'k (fraction)' / 'p (index)', and an
        # unconvertible unit ('psig', 'm2', 'poise') must not be reported as one.
        if clean_unit_name(unit) in KNOWN_UNITS[kind]:
            return kind, unit

    return None

def normalize_value(val: float, prop_type: str, unit: str) -> float:
    if prop_type == "pressure":
        return convert_pressure(val, unit)
    elif prop_type == "temperature":
        return convert_temperature(val, unit)
    elif prop_type == "permeability":
        return convert_permeability(val, unit)
    elif prop_type == "viscosity":
        return convert_viscosity(val, unit)
    return val
