import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from assistant import tools  # noqa: E402


@pytest.mark.parametrize("tool", tools.TOOLS, ids=lambda t: t.name)
def test_tool_parameters_match_the_function_signature(tool):
    signature = inspect.signature(tool.run).parameters
    assert set(tool.parameters) == set(signature)
    for name, param in tool.parameters.items():
        has_default = signature[name].default is not inspect.Parameter.empty
        # The model may be stricter than Python (region), but never looser.
        assert param.required or has_default, f"{tool.name}.{name} is optional but has no default"


def test_registry_is_keyed_by_tool_name():
    assert all(name == tool.name for name, tool in tools.REGISTRY.items())
    assert len(tools.REGISTRY) == len(tools.TOOLS)
