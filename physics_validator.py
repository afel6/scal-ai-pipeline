class PhysicsEngineError(Exception):
    pass

class PhysicsValidator:
    """
    Deterministic logic gate protecting the algorithms from AI hallucinations.
    """
    
    @staticmethod
    def format_precision(value: float, decimals: int = 4) -> float:
        return round(float(value), decimals)

    @staticmethod
    def validate_core_physics(data: dict) -> dict:
        swi = PhysicsValidator.format_precision(data.get('Swi', 0.0))
        sor = PhysicsValidator.format_precision(data.get('Sor', 0.0))
        porosity = PhysicsValidator.format_precision(data.get('Porosity', 0.0))
        
        if swi + sor > 1.0:
            raise PhysicsEngineError(
                f"PHYSICS VIOLATION: Swi ({swi}) + Sor ({sor}) = {swi + sor}. "
                "Total fluid saturation cannot mathematically exceed 1.0."
            )
            
        if porosity >= 1.0 or porosity <= 0.0:
            raise PhysicsEngineError(
                f"PHYSICS VIOLATION: Porosity ({porosity}) must be a fractional value between 0.0001 and 0.9999."
            )
            
        return {k: PhysicsValidator.format_precision(v) for k, v in data.items()}
