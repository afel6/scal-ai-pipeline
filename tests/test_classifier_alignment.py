"""Alignment test: file_reader._detect_test_type must classify with the same
weighted keyword scoring as SCALFileHandler.identify (scal_file_handler.py),
then map the handler's type key onto the file_reader vocabulary:

    MICP -> MICP, KR -> REL_PERM, PC -> IMBIBITION,
    FDAM -> KW_THROUGHPUT, RCAL -> overburden_compaction.
"""

from file_reader import _detect_test_type


def test_classifier_alignment_mock_text():
    # Raw text snippets representative of each SCAL test type, mapped to the
    # file_reader type key the aligned classifier must resolve to.
    snippets = {
        # MICP: mercury injection vocabulary, no PC high-weight words.
        "MICP": (
            "Mercury intrusion porosimetry with cumulative intrusion versus "
            "pressure psia, pore throat radius from the Washburn equation, "
            "threshold pressure pick"
        ),
        # KR -> REL_PERM: relative permeability endpoints and curves.
        "REL_PERM": (
            "Relative permeability water flood test: kro krw versus water "
            "saturation, end point sor and swi reported"
        ),
        # PC -> IMBIBITION: centrifuge vocabulary carries 10x weights.
        "IMBIBITION": (
            "Centrifuge capillary pressure drainage cycle, speed in rpm and "
            "produced volume recorded per step, air-brine system"
        ),
        # FDAM -> KW_THROUGHPUT: sensitivity test (10x) + kl (5x).
        "KW_THROUGHPUT": (
            "Fluid sensitivity test formation damage screening, kl in mD "
            "versus cum.pv.inj of brine"
        ),
        # RCAL -> overburden_compaction: routine-core / overburden vocabulary.
        "overburden_compaction": (
            "Routine core analysis: klinkenberg air permeability and grain "
            "density per plug, horizontal perm and vertical perm at obp, "
            "compaction and compressibility trends"
        ),
    }

    for expected, text in snippets.items():
        detected = _detect_test_type("mock.xlsx", ["Sheet1"], text)
        assert detected == expected, (
            f"snippet for {expected!r} classified as {detected!r}"
        )

    # No SCAL vocabulary at all -> UNKNOWN.
    assert _detect_test_type("mock.xlsx", ["Sheet1"], "lorem ipsum dolor") == "UNKNOWN"

    # Handler types with no file_reader equivalent (e.g. NMR) also map to UNKNOWN.
    nmr_text = "NMR t2 distribution relaxation bvi ffi free fluid t2 cutoff"
    assert _detect_test_type("mock.xlsx", ["Sheet1"], nmr_text) == "UNKNOWN"
