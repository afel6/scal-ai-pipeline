class PhysicsEngine:
    """
    Validates fluid saturations and enforces engineering precision.
    """
    @staticmethod
    def validate_saturations(swi, sor):
        """
        Physics Check: Swi + Sor <= 1.0
        Raises a ValueError if data is physically impossible.
        """
        total_saturation = swi + sor
        if total_saturation > 1.0:
            raise ValueError(f"Physics Violation: Swi ({swi}) + Sor ({sor}) = {total_saturation} > 1.0")
        return True
    
    @staticmethod
    def format_precision(value):
        """
        Enforces exactly 4 decimal places for all SCAL constants.
        """
        return float(f"{value:.4f}")
