import re
from typing import Dict, Any, Tuple, Optional, List

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

def clean_unit_name(name: str) -> str:
    # Normalize unit name: lowercase, strip symbols/spaces
    u = name.lower().strip()
    u = u.replace("°", "").replace("deg", "")
    return u

def convert_pressure(val: float, from_unit: str) -> float:
    u = clean_unit_name(from_unit)
    factor = PRESSURE_FACTORS.get(u, 1.0)
    return val * factor

def convert_temperature(val: float, from_unit: str) -> float:
    u = clean_unit_name(from_unit)
    if u in ("c", "celsius"):
        return val * 9.0 / 5.0 + 32.0
    elif u in ("k", "kelvin"):
        return (val - 273.15) * 9.0 / 5.0 + 32.0
    return val

def convert_permeability(val: float, from_unit: str) -> float:
    u = clean_unit_name(from_unit)
    factor = PERM_FACTORS.get(u, 1.0)
    return val * factor

def convert_viscosity(val: float, from_unit: str) -> float:
    u = clean_unit_name(from_unit)
    factor = VISCOSITY_FACTORS.get(u, 1.0)
    return val * factor

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
            return "pressure", unit
        elif prop in ("t", "temp", "temperature"):
            return "temperature", unit
        elif prop in ("k", "perm", "permeability"):
            return "permeability", unit
        elif prop in ("viscosity",):
            return "viscosity", unit
            
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
