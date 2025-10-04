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

import pathlib

import pytest
import yaml
from pytest_inmanta.plugin import Project

from inmanta_plugins.git_ops import const
from inmanta_plugins.git_ops.store import SliceStore


def test_basics(project: Project) -> None:
    project.compile("import git_ops")


def test_unroll_slices(
    project: Project, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Define a basic store
    store = SliceStore(
        "test",
        folder="file://" + str(tmp_path / "test"),
    )

    model = """
        import git_ops
        import unittest

        for slice in git_ops::unroll_slices("test"):
            unittest::Resource(
                name=slice.store_name + ":" + slice.identifier,
                desired_value=std::json_dumps(slice.attributes),
            )
        end
    """

    # Empty store should work just fine
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", "activate")
        project.compile(model, no_dedent=False)

    # Add some one slice to the folder
    s1 = store.source_path / "s1.yaml"
    s1.write_text(yaml.safe_dump({"a": 0}))

    # Compile with one slice should now produce one resource
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", "activate")
        project.compile(model, no_dedent=False)

    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert r1.desired_value == '{"a": 0}'

    # Add some another slice to the folder
    s2 = store.source_path / "s2.yaml"
    s2.write_text(yaml.safe_dump({"a": 1}))

    # Compile should still work, slices should be differentiated
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", "activate")
        project.compile(model, no_dedent=False)

    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert r1.desired_value == '{"a": 0}'
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None
    assert r2.desired_value == '{"a": 1}'
