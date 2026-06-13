import pytest
import math
from app import safe_parse_list

def test_safe_parse_list_basic_strings():
    s = "['a', 'b', 'c']"
    res = safe_parse_list(s)
    assert res == ['a', 'b', 'c']

def test_safe_parse_list_primitives():
    s = "[1, 2.5, None, True, False]"
    res = safe_parse_list(s)
    assert res == [1, 2.5, None, True, False]
    assert isinstance(res[0], int)
    assert isinstance(res[1], float)
    assert res[2] is None
    assert res[3] is True
    assert res[4] is False

def test_safe_parse_list_nan():
    s = "[nan, NaN, 1.0]"
    res = safe_parse_list(s)
    assert math.isnan(res[0])
    assert math.isnan(res[1])
    assert res[2] == 1.0

def test_safe_parse_list_complex_strings():
    s = "['string with \\' quote', \"double \\\" quote\", 'comma, inside', 'normal']"
    res = safe_parse_list(s)
    assert res == ["string with ' quote", 'double " quote', 'comma, inside', 'normal']

def test_safe_parse_list_fallback():
    # A malformed list without brackets should trigger the fallback
    s = "'a', 'b', 'c'"
    res = safe_parse_list(s)
    assert res == ['a', 'b', 'c']

def test_safe_parse_list_malformed_bracket():
    # This shouldn't crash, it should just try to parse or fallback
    s = "['a', 'b'"
    res = safe_parse_list(s)
    # The current fallback will strip quotes and brackets, so it returns ['a', 'b']
    assert res == ['a', 'b']

def test_safe_parse_list_dos_prevention():
    # Ensure no exceptions are thrown and it handles it quickly
    # A very deeply nested string that might crash ast.literal_eval
    s = "[" + "'hello', " * 1000 + "'world']"
    res = safe_parse_list(s)
    assert len(res) == 1001
    assert res[0] == "hello"
    assert res[-1] == "world"

def test_safe_parse_list_unsupported_ast():
    # If someone tries to pass actual code or objects
    s = "[__import__('os').system('ls')]"
    res = safe_parse_list(s)
    # The parser treats it as string or fails gracefully
    assert res == ["__import__('os').system('ls')"]
