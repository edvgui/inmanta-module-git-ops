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

import json
import pathlib

import pytest
import yaml
from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice
from pytest_inmanta.plugin import Project

from inmanta_plugins.git_ops import const
from inmanta_plugins.git_ops.store import SliceStore


def test_unroll_slices(
    project: Project, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Define a basic store
    store = SliceStore(
        name="test",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    model = """
        import git_ops
        import git_ops::processors
        import unittest

        for slice in git_ops::unroll_slices("test"):
            attributes = slice["attributes"]
            unique_id = attributes["operation"] == "delete"
                ? attributes["unique_id"]
                : git_ops::processors::unique_integer(
                    slice["store_name"],
                    slice["name"],
                    "unique_id",
                    used_integers=git_ops::processors::used_values(
                        slice["store_name"],
                        "unique_id",
                    ),
                )

            unittest::Resource(
                name=slice["store_name"] + ":" + slice["name"],
                desired_value=std::json_dumps(
                    {
                        "name": attributes["name"],
                        "description": attributes["description"],
                        "unique_id": unique_id,
                        "operation": attributes["operation"],
                        "path": attributes["path"],
                        "version": attributes["version"],
                        "embedded_required": attributes["embedded_required"],
                        "embedded_optional": attributes["embedded_optional"],
                        "embedded_sequence": attributes["embedded_sequence"],
                    }
                ),
            )
        end
    """

    # Empty store should work just fine
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

    # Add some one slice to the folder
    s1_obj = Slice(
        name="a",
        embedded_required=EmbeddedSlice(
            name="aa",
        ),
    )
    s1 = store.source_path / "s1.yaml"
    s1.write_text(yaml.safe_dump(s1_obj.model_dump(mode="json")))
    s1_v1 = store.active_path / "s1@v1.json"
    s1_v2 = store.active_path / "s1@v2.json"

    # Compile with one slice should now produce one resource
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

    assert not s1_v1.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": None,
        "unique_id": 0,
        "operation": "create",
        "path": ".",
        "version": 1,
        "embedded_required": {
            "operation": "create",
            "path": "embedded_required",
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }

    # Add some another slice to the folder
    s2_obj = Slice(
        name="b",
        embedded_required=EmbeddedSlice(
            name="bb",
        ),
    )
    s2 = store.source_path / "s2.yaml"
    s2.write_text(yaml.safe_dump(s2_obj.model_dump(mode="json")))
    s2_v1 = store.active_path / "s2@v1.json"
    s2_v2 = store.active_path / "s2@v2.json"

    # Compile should still work, slices should be differentiated
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

    assert not s1_v1.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": None,
        "unique_id": 0,
        "operation": "create",
        "path": ".",
        "version": 1,
        "embedded_required": {
            "operation": "create",
            "path": "embedded_required",
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    assert yaml.safe_load(s1.read_text()) == {
        "name": "a",
        "description": None,
        "unique_id": 0,
        "embedded_required": {
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    assert not s2_v1.exists()
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None
    assert json.loads(r2.desired_value) == {
        "name": "b",
        "description": None,
        "unique_id": 1,
        "operation": "create",
        "path": ".",
        "version": 1,
        "embedded_required": {
            "operation": "create",
            "path": "embedded_required",
            "name": "bb",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    assert yaml.safe_load(s2.read_text()) == {
        "name": "b",
        "description": None,
        "unique_id": 1,
        "embedded_required": {
            "name": "bb",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }

    # Nothing has been synced, exporting compile should not have any resource
    project.compile(model, no_dedent=False)
    assert not project.resources

    # Sync the changes
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert not s1_v2.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert s2_v1.exists()
    assert not s2_v2.exists()
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None

    # Exporting compile should now have all the resources
    project.compile(model, no_dedent=False)

    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None

    # Second sync shouldn't change anything
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert not s1_v2.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert s2_v1.exists()
    assert not s2_v2.exists()
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None

    # Update first slice
    s1_obj = Slice(**yaml.safe_load(s1.read_text()))
    s1_obj.description = "Updated"
    s1_obj.embedded_optional = EmbeddedSlice(name="ab")
    s1_obj.embedded_sequence = [EmbeddedSlice(name="ac")]
    s1.write_text(yaml.safe_dump(s1_obj.model_dump(mode="json")))

    # Sync changes
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert s1_v2.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": "Updated",
        "unique_id": 0,
        "operation": "update",
        "path": ".",
        "version": 2,
        "embedded_required": {
            "operation": "update",
            "path": "embedded_required",
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": {
            "operation": "create",
            "path": "embedded_optional",
            "name": "ab",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_sequence": [
            {
                "operation": "create",
                "path": "embedded_sequence[name=ac]",
                "name": "ac",
                "description": None,
                "unique_id": None,
                "recursive_slice": [],
            }
        ],
    }
    assert s2_v1.exists()
    assert not s2_v2.exists()
    r2 = project.get_resource("unittest::Resource", name="test:s2")
    assert r2 is not None
    assert json.loads(r2.desired_value) == {
        "name": "b",
        "description": None,
        "unique_id": 1,
        "operation": "create",
        "path": ".",
        "version": 1,
        "embedded_required": {
            "operation": "create",
            "path": "embedded_required",
            "name": "bb",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }

    # Delete a slice
    s1.unlink()
    s1_v3 = store.active_path / "s1@v3.json"

    # Sync changes
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert s1_v2.exists()
    assert s1_v3.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": "Updated",
        "unique_id": 0,
        "operation": "delete",
        "path": ".",
        "version": 3,
        "embedded_required": {
            "operation": "delete",
            "path": "embedded_required",
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": {
            "operation": "delete",
            "path": "embedded_optional",
            "name": "ab",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_sequence": [
            {
                "operation": "delete",
                "path": "embedded_sequence[name=ac]",
                "name": "ac",
                "description": None,
                "unique_id": None,
                "recursive_slice": [],
            }
        ],
    }
