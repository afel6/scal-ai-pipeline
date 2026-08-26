from scal_file_handler import sanitize_well_hallucinations

def test_empty_input():
    assert sanitize_well_hallucinations("") == ""
    assert sanitize_well_hallucinations(None) is None

def test_rule_0_clay_terms():
    assert sanitize_well_hallucinations("Clay swelling occurs here.") == "Clay hydration occurs here."
    assert sanitize_well_hallucinations("The clay swells in water.") == "The clay expands in water."
    assert sanitize_well_hallucinations("It will swell.") == "It will expand."
    assert sanitize_well_hallucinations("We dwell on this point.") == "We remain on this point."
    # Case insensitivity
    assert sanitize_well_hallucinations("SWELLING SWELLS SWELL DWELL") == "hydration expands expand remain"
    # Boundaries (e.g. "dwelling" should not be touched unless we add a rule for it, current rule is \bdwell\b)
    # The rule is `\bdwell\b`, so "dwelling" remains "dwelling"
    assert sanitize_well_hallucinations("dwelling") == "dwelling"

def test_rule_1_safe_phrases():
    assert sanitize_well_hallucinations("Prices are well above average.") == "Prices are significantly above average."
    assert sanitize_well_hallucinations("Temperatures are well below zero.") == "Temperatures are significantly below zero."
    assert sanitize_well_hallucinations("A as well as B.") == "A along with B."
    assert sanitize_well_hallucinations("They are well aligned.") == "They are strongly aligned."
    assert sanitize_well_hallucinations("The data was well analyzed.") == "The data was thoroughly analyzed."
    assert sanitize_well_hallucinations("The data was well analysed.") == "The data was thoroughly analysed."
    assert sanitize_well_hallucinations("It is well adjusted.") == "It is properly adjusted."
    assert sanitize_well_hallucinations("Tasks are well assigned.") == "Tasks are properly assigned."

    assert sanitize_well_hallucinations("He is well behaved.") == "He is well-behaved."
    assert sanitize_well_hallucinations("The well behavior is normal.") == "The wellbore behavior is normal."
    assert sanitize_well_hallucinations("The well behaviour is normal.") == "The wellbore behaviour is normal."
    assert sanitize_well_hallucinations("The well bore is clean.") == "The wellbore is clean."

    # Case insensitivity for phrases
    assert sanitize_well_hallucinations("Well Above") == "significantly above"
    assert sanitize_well_hallucinations("AS WELL AS") == "along with"

def test_rule_2_fallback():
    # word starting with a
    assert sanitize_well_hallucinations("The well axis is vertical.") == "The reservoir axis is vertical."
    assert sanitize_well_hallucinations("Well arrow pointing up.") == "Reservoir arrow pointing up."

    # word starting with b
    assert sanitize_well_hallucinations("The well boundary is reached.") == "The reservoir boundary is reached."
    assert sanitize_well_hallucinations("WELL Bounded") == "RESERVOIR Bounded"

    # Capitalization handling by rule 2
    assert sanitize_well_hallucinations("Well axis") == "Reservoir axis"
    assert sanitize_well_hallucinations("WELL AXIS") == "RESERVOIR AXIS"
    assert sanitize_well_hallucinations("well Axis") == "reservoir Axis"

    # Ensures no trigger for non a/b words
    assert sanitize_well_hallucinations("The well casing is new.") == "The well casing is new."
