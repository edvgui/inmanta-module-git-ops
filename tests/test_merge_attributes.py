"""
Copyright 2025 Guillaume Everarts de Velp

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Contact: edvgui@gmail.com
"""

import pytest

from inmanta.util import dict_path
from inmanta_plugins.git_ops.store import merge_attributes


@pytest.mark.parametrize(
    ("current", "previous", "result"),
    [
        (
            {"a": 0},
            [{"a": 1}],
            {"a": 0, "_path": "."},
        ),
        (
            {"a": None},
            [{"a": 1}],
            {"a": None, "_path": "."},
        ),
        (
            {"a": None},
            [{"b": 1}],
            {"a": None, "b": None, "_path": "."},
        ),
        (
            {"a": None},
            [{"a": {"a": 0}}],
            {"a": {"a": 0, "_purged": True, "_path": "a"}, "_path": "."},
        ),
        (
            {"a": None},
            [{"a": {"a": 0}}, {"a": {"a": 0}}],
            {"a": {"a": 0, "_purged": True, "_path": "a"}, "_path": "."},
        ),
        (
            {"a": None},
            [{"a": {"a": 0}}, {"a": {"b": 0}}],
            {"a": {"a": 0, "b": None, "_purged": True, "_path": "a"}, "_path": "."},
        ),
        (
            {"a": None},
            [{"a": {"a": 0}}, {"b": {"b": 0}}],
            {
                "a": {"a": 0, "_purged": True, "_path": "a"},
                "b": {"b": 0, "_purged": True, "_path": "b"},
                "_path": ".",
            },
        ),
        (
            {"a": {"a": None}},
            [{"a": {"a": {"a": None}}}, {"b": {"b": 0}}],
            {
                "a": {"a": {"a": None, "_purged": True, "_path": "a.a"}, "_path": "a"},
                "b": {"b": 0, "_purged": True, "_path": "b"},
                "_path": ".",
            },
        ),
        (
            {"a": {"a": None}},
            [{"a": {"a": {"a": None}}}, {"a": {"a": None}}],
            {
                "a": {"a": {"a": None, "_purged": True, "_path": "a.a"}, "_path": "a"},
                "_path": ".",
            },
        ),
        (
            {"a": {"a": None}},
            [{"a": {"a": None}}, {"a": {"a": {"a": None}}}],
            {
                "a": {"a": {"a": None, "_purged": True, "_path": "a.a"}, "_path": "a"},
                "_path": ".",
            },
        ),
    ],
)
def test_basics(current: dict, previous: list[dict], result: dict) -> None:
    assert (
        merge_attributes(
            current,
            previous,
            path=dict_path.NullPath(),
        )
        == result
    )
