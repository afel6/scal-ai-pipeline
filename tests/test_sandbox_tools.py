import pytest
import json
from app import PRCChatAssistant

class DummyCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args

def test_sandbox_fit_brooks_corey_execution():
    assistant = PRCChatAssistant(keys=["DUMMY_KEY"])
    # Mock some data points
    sw = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    krw = [0.0, 0.01, 0.05, 0.12, 0.22, 0.35, 0.5]
    kro = [0.8, 0.6, 0.4, 0.22, 0.1, 0.02, 0.0]
    
    call = DummyCall("sandbox_fit_brooks_corey", {
        "sw": sw,
        "krw": krw,
        "kro": kro,
        "swi": 0.2,
        "sor": 0.2,
        "krw_max": 0.5,
        "kro_max": 0.8,
        "sample_name": "Test-Core"
    })
    
    # Run tool execution
    generator = assistant._execute_tool(call)
    res_list = list(generator)
    assert len(res_list) > 0
    is_final, result = res_list[-1]
    assert is_final is True
    
    fit_res = json.loads(result)
    assert "parameters" in fit_res
    assert "coordinates" in fit_res
    
    # Test formatting
    fmt = assistant._format_tool_response("sandbox_fit_brooks_corey", call.args, result)
    assert "__PRC_PLOT__" in fmt

def test_sandbox_fit_archie_execution():
    assistant = PRCChatAssistant(keys=["DUMMY_KEY"])
    # Mock Sw and RI data
    x = [0.2, 0.4, 0.6, 0.8, 1.0]
    y = [25.0, 6.25, 2.78, 1.56, 1.0]
    
    call = DummyCall("sandbox_fit_archie", {
        "x": x,
        "y": y,
        "model_type": "RI",
        "sample_name": "Test-Core"
    })
    
    generator = assistant._execute_tool(call)
    res_list = list(generator)
    assert len(res_list) > 0
    is_final, result = res_list[-1]
    assert is_final is True
    
    fit_res = json.loads(result)
    assert "parameters" in fit_res
    
    fmt = assistant._format_tool_response("sandbox_fit_archie", call.args, result)
    assert "__PRC_PLOT__" in fmt
