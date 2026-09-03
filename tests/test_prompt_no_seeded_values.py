"""The system prompt must not seed sample-specific answers (audit finding A2).

Measured contamination before this guard existed: asked for the saturation
exponent of an unrelated sample whose data fits n = 1.85, the model asserted
the prompt's hardcoded n = 2.14 in 3/5 runs on the real prompt and 4/5 with
only the answer-key block removed. The illustrative `such as $n=2.14$` was
sufficient on its own to seed the value, so every occurrence has to go, not
just the answer key.

Guidance about *reasoning* is welcome in the prompt. Specific numeric results
tied to a named sample are not: the model recites them for other samples.
"""

from pathlib import Path
from typing import List

import pytest


PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "hviel_system_prompt.md"

# Values the prompt previously asserted for named samples Y4 / Y2. Each one was
# reproduced verbatim on an unrelated sample, or is a companion value from the
# same answer-key block.
SEEDED_VALUES: List[str] = [
    "2.14",     # Archie saturation exponent, Sample Y4
    "-0.05",    # Amott-Harvey index, Sample Y2
    "-0.32",    # USBM index, Sample Y2
    "0.44",     # the IAH value the prompt forbade, still a recitable number
    "8130",     # Sample Y4 depth
    "0.085",    # Sample Y4 Sw under n = 2.0
    "0.100",    # Sample Y4 Sw under the fitted n
    "1.876",    # decimal-formatting example; observed recited as a fitted n
    "16.86",    # decimal-formatting example for porosity, same hazard
    "0.9150",   # Dykstra-Parsons, Well-Y base case
    "0.6245",   # Lorenz, Well-Y base case
    "0.9339",   # Dykstra-Parsons, Well-Y confining stress
    "0.6344",   # Lorenz, Well-Y confining stress
]

SEEDED_SAMPLE_NAMES: List[str] = ["Sample Y4", "Sample Y2", "Well-Y", "sample X5"]


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", SEEDED_VALUES)
def test_prompt_states_no_seeded_parameter_value(prompt_text: str, value: str) -> None:
    """No hardcoded result a model could recite for a different sample."""
    hits = [f"line {i}" for i, line in enumerate(prompt_text.splitlines(), 1)
            if value in line]
    assert not hits, (
        f"seeded value {value!r} still present at {hits}; "
        "replace it with a placeholder such as `<fitted value>` or a range"
    )


@pytest.mark.parametrize("name", SEEDED_SAMPLE_NAMES)
def test_prompt_names_no_seeded_sample(prompt_text: str, name: str) -> None:
    """Worked examples must not be pinned to a specific named sample."""
    hits = [f"line {i}" for i, line in enumerate(prompt_text.splitlines(), 1)
            if name in line]
    assert not hits, f"seeded sample name {name!r} still present at {hits}"


def test_prompt_keeps_the_general_archie_reasoning(prompt_text: str) -> None:
    """Removing the numbers must not remove the rule they illustrated."""
    assert "underestimates" in prompt_text
    assert "laboratory-fitted n value" in prompt_text


def test_prompt_keeps_the_wettability_congruency_rule(prompt_text: str) -> None:
    """The executive-summary congruency rule survives without the Y2 numbers."""
    assert "USBM" in prompt_text
    assert "Amott-Harvey" in prompt_text
