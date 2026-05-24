import pandas as pd
from typing import Dict, Any

class BaseExtractor:
    """
    Abstract base class for all SCAL data extractors.
    Each SCAL format (MICP, KR, FRF, etc.) implements its own extractor subclass.
    """
    def __init__(self, raw_data: Dict[str, pd.DataFrame]):
        self.raw_data = raw_data
        self.extracted = {}

    def extract(self) -> Dict[str, Any]:
        """
        Processes raw DataFrame sheets and returns a dictionary of extracted,
        cleaned, and standardized parameters.
        """
        raise NotImplementedError("Subclasses must implement the extract method.")
