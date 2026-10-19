from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "bedrock_benchmark.py"
_SPEC = spec_from_file_location("bedrock_benchmark", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_benchmark_rubric_requires_all_case_terms() -> None:
    case = _MODULE.benchmark_cases()[0]

    assert _MODULE._rubric_pass(
        case, "The fee concern is acknowledged and the issue is resolved."
    )
    assert not _MODULE._rubric_pass(case, "The fee concern is acknowledged.")
