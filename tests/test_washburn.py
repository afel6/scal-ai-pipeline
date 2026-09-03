import pytest
from prc_physics import calculate_washburn_radius

def test_washburn_calculation():
    # Test a typical reservoir pressure of 100 psia
    # r = (2 * 480 * |cos(140)|) / (100 * 68947.6) * 10000
    # cos(140) = -0.766044
    # r = (2 * 480 * 0.766044) / 6894760 * 10000 = 735.402 / 6894760 * 10000 = 1.0666 microns
    # Let's verify precision:
    radius = calculate_washburn_radius(100.0)
    assert radius == 1.0666
    
    # Test extremely high pressure
    radius_high = calculate_washburn_radius(10000.0)
    assert radius_high == 0.0107
    
    # Test extremely low positive pressure
    radius_low = calculate_washburn_radius(0.1)
    assert radius_low == 1066.611

def test_washburn_boundaries():
    # Test negative pressure raises ValueError
    with pytest.raises(ValueError, match="positive"):
        calculate_washburn_radius(-5.0)
        
    # Zero pressure has no pore radius (D3.1): a refusal, not a 1e-9 substitution
    # that returned a ~10^12 micron "radius".
    with pytest.raises(ValueError):
        calculate_washburn_radius(0.0)

def test_washburn_custom_parameters():
    # Test with custom contact angle and IFT
    # theta = 130 deg, IFT = 485 dynes/cm
    # cos(130) = -0.6427876
    # r = (2 * 485 * 0.6427876) / (100 * 68947.6) * 10000 = 0.9043 microns
    radius = calculate_washburn_radius(100.0, contact_angle_deg=130.0, interfacial_tension=485.0)
    assert radius == 0.9043
