"""B5 — the dead Genkit registration is gone, killing the double-registration.

All ten tool names were registered twice: once as `_HVIEL_TOOLS` schemas that
the NVIDIA path actually sends and `_execute_tool` implements, and once as
`@ai.tool` Genkit stubs returning placeholder strings ("Calculated", "Fitted",
...). Nothing calls `ai.generate`, so the stubs were inert — but a future switch
to Genkit's own loop would have every tool call resolve to a placeholder that
`_tool_result_error` classifies as success. Removing the Genkit object and the
stubs leaves exactly one registration: the real one.
"""
import app


def test_genkit_object_removed():
    assert not hasattr(app, "ai"), "the Genkit `ai` object must be gone"
    assert not hasattr(app, "google_ai_plugin"), "the GoogleAI plugin must be gone"


def test_no_placeholder_tool_stubs():
    for stub in ("calculate_petrophysics_properties_tool",
                 "execute_python_simulation_tool",
                 "generate_mermaid_diagram_tool",
                 "fit_petrophysical_curve_tool",
                 "agentic_history_matching_tool",
                 "generate_executive_report_tool",
                 "get_audit_history_tool"):
        assert not hasattr(app, stub), f"placeholder stub {stub} must be removed"


def test_tools_still_declared_once_for_the_model():
    # The real single registration — the schema list the provider is sent —
    # still carries all ten tool names.
    names = {t["function"]["name"] for t in app._chat_tools()}
    for expected in ("calculate_petrophysics_properties", "execute_python_simulation",
                     "generate_mermaid_diagram", "fit_petrophysical_curve",
                     "agentic_history_matching", "generate_executive_report",
                     "get_audit_history", "sandbox_fit_brooks_corey",
                     "sandbox_fit_archie", "hybrid_geological_search"):
        assert expected in names, f"{expected} missing from the real tool declaration"
