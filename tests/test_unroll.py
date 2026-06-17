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

import copy
import json
import pathlib

import pytest
import yaml
from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice
from pytest_inmanta.plugin import Project

from inmanta_plugins.git_ops import config, const
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
            unique_id = git_ops::processors::unique_integer(
                slice["store_name"],
                slice["name"],
                "unique_id",
                used_integers=git_ops::processors::used_values(
                    slice["store_name"],
                    "unique_id",
                ),
            )

            for embedded in attributes["embedded_sequence"]:
                git_ops::processors::unique_integer(
                    slice["store_name"],
                    slice["name"],
                    embedded["path"] + ".unique_id",
                    used_integers=git_ops::processors::used_values(
                        slice["store_name"],
                        "embedded_sequence[name=*].unique_id",
                        slice_matching={"unique_id": unique_id},
                    ),
                )
            end

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

    # Compile with default store config, no schema should be created
    schema_path = tmp_path / "schema" / "test.json"
    assert not schema_path.exists()

    # Add config that includes a schema path, compile should create the schema file with the correct content
    conf = config.GitOpsConfig(
        stores=[
            config.SliceStoreConfig(
                store_name="test",
                schema_path="file://" + str(schema_path),
            )
        ]
    )
    conf.path().parent.mkdir(parents=True, exist_ok=True)
    conf.save()

    # Empty store should work just fine
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

    # Validate that the schema file has been created with the correct content
    assert schema_path.exists()
    assert json.loads(schema_path.read_text()) == Slice.model_json_schema()

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

    # And export
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
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    # And export
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
            "operation": "create",
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
                "unique_id": 0,
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

    # Delete embedded entity
    s1_obj.embedded_sequence = []
    s1.write_text(yaml.safe_dump(s1_obj.model_dump(mode="json")))
    s1_v3 = store.active_path / "s1@v3.json"

    # Sync changes
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert s1_v2.exists()
    assert s1_v3.exists()
    assert json.loads(s1_v3.read_text()) == {
        "name": "a",
        "description": "Updated",
        "unique_id": 0,
        "embedded_required": {
            "name": "aa",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": {
            "name": "ab",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_sequence": [],
    }

    # And export
    project.compile(model, no_dedent=False)

    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": "Updated",
        "unique_id": 0,
        "operation": "update",
        "path": ".",
        "version": 3,
        "embedded_required": {
            "operation": "create",
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
                "operation": "delete",
                "path": "embedded_sequence[name=ac]",
                "name": "ac",
                "description": None,
                "unique_id": 0,
                "recursive_slice": [],
            }
        ],
    }

    # Delete a slice
    s1.unlink()
    s1_v4 = store.active_path / "s1@v3.json"

    # Sync changes
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    # And export
    project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert s1_v2.exists()
    assert s1_v3.exists()
    assert s1_v4.exists()
    r1 = project.get_resource("unittest::Resource", name="test:s1")
    assert r1 is not None
    assert json.loads(r1.desired_value) == {
        "name": "a",
        "description": "Updated",
        "unique_id": 0,
        "operation": "delete",
        "path": ".",
        "version": 4,
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
                "unique_id": 0,
                "recursive_slice": [],
            }
        ],
    }


def test_desired_state_stability(project: Project, tmp_path: pathlib.Path) -> None:
    """
    Make sure the unrolling of slices always produces the same
    desired state.
    """
    # Define a basic store
    store = SliceStore(
        name="test2",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    model = """
        import git_ops
        import git_ops::processors
        import unittest

        unittest::Resource(
            name="test2",
            desired_value=std::json_dumps(
                [
                    slice["attributes"]
                    for slice in git_ops::unroll_slices("test2")
                ]
            )
        )
    """

    base_attrs = ["operation", "path", "version", "slice_store", "slice_name"]

    def remove_base_attrs(slice: object) -> object:
        match slice:
            case dict():
                return {
                    k: remove_base_attrs(v)
                    for k, v in slice.items()
                    if k not in base_attrs
                }
            case list():
                return [remove_base_attrs(v) for v in slice]
            case _:
                return slice

    def desired_state_value() -> object:
        project.compile(model, no_dedent=False)
        resource = project.get_resource("unittest::Resource")
        assert resource is not None
        return remove_base_attrs(json.loads(resource.desired_value))

    # Empty store
    assert desired_state_value() == []

    # Add a first slice to the store
    a = store.active_path / "a@v1.json"
    a_val = {
        "name": "a",
        "description": None,
        "unique_id": None,
        "embedded_required": {
            "name": "a",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    a.write_text(json.dumps(a_val))
    assert desired_state_value() == [a_val]

    # Add a second slice, make sure the order of the slices is consistent
    b = store.active_path / "b@v1.json"
    b_val = {
        "name": "a",
        "description": None,
        "unique_id": None,
        "embedded_required": {
            "name": "a",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    b.write_text(json.dumps(b_val))
    assert desired_state_value() == [a_val, b_val]

    # Add embedded slices, make sure their ordering stays consistent
    a_val["embedded_sequence"] = [
        {
            "name": "a",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        {
            "name": "c",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        {
            "name": "b",
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
    ]
    a.write_text(json.dumps(a_val))
    assert desired_state_value() == [a_val, b_val]

    # Add a newer version of a, which contains less embedded entities
    # the merging of old and new desired state should stay consistent
    a_v2 = store.active_path / "a@v2.json"
    a_v2_val = copy.deepcopy(a_val)

    # Pop the first element
    a_v2_val["embedded_sequence"] = a_v2_val["embedded_sequence"][1:]
    a_v2.write_text(json.dumps(a_v2_val))

    # New value should still include the deleted element, but it will be
    # moved to the end of the list as deleted elements are inserted last
    a_merged_val = copy.deepcopy(a_v2_val)
    a_merged_val["embedded_sequence"].append(a_val["embedded_sequence"][0])
    assert desired_state_value() == [a_merged_val, b_val]


def _embedded(
    name: str,
    description: str | None = None,
    recursive_slice: list[dict] | None = None,
) -> dict:
    """
    Build the source attributes of an example::slices::recursive::EmbeddedSlice.
    """
    return {
        "name": name,
        "description": description,
        "unique_id": None,
        "recursive_slice": recursive_slice if recursive_slice is not None else [],
    }


def _operations_by_path(project: Project, store_name: str) -> dict[str, str]:
    """
    Compile a model that unrolls the slices of the given store and return a
    mapping from the path of every slice element to the operation attached to
    it.  The store is expected to contain a single slice.
    """
    model = f"""
        import git_ops
        import unittest

        unittest::Resource(
            name="{store_name}",
            desired_value=std::json_dumps(
                [
                    slice["attributes"]
                    for slice in git_ops::unroll_slices("{store_name}")
                ]
            )
        )
    """
    project.compile(model, no_dedent=False)
    resource = project.get_resource("unittest::Resource")
    assert resource is not None

    operations: dict[str, str] = {}

    def collect(element: object) -> None:
        if isinstance(element, dict):
            if "operation" in element and "path" in element:
                operations[element["path"]] = element["operation"]
            for value in element.values():
                collect(value)
        elif isinstance(element, list):
            for value in element:
                collect(value)

    collect(json.loads(resource.desired_value))
    return operations


def test_update_operation_only_on_changed_content(
    project: Project, tmp_path: pathlib.Path
) -> None:
    """
    When a slice gains a new version, the "update" operation must only be
    attached to the slice elements whose content actually changed.  Unchanged
    elements keep the "create" operation, new elements are created and removed
    elements are deleted.
    """
    store = SliceStore(
        name="test_scope",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    # The empty store unrolls to nothing (and the active folder gets created).
    assert _operations_by_path(project, store.name) == {}

    # First version: everything is created.
    a_v1 = {
        "name": "a",
        "description": None,
        "unique_id": None,
        "embedded_required": _embedded("req"),
        "embedded_optional": None,
        "embedded_sequence": [_embedded("x", "1"), _embedded("y", "1")],
    }
    (store.active_path / "a@v1.json").write_text(json.dumps(a_v1))
    assert _operations_by_path(project, store.name) == {
        ".": "create",
        "embedded_required": "create",
        "embedded_sequence[name=x]": "create",
        "embedded_sequence[name=y]": "create",
    }

    # Second version: change x, leave y and embedded_required untouched, and
    # add an optional embedded slice.  Only the slice itself, x and the new
    # optional slice carry a change.
    a_v2 = copy.deepcopy(a_v1)
    a_v2["embedded_sequence"][0]["description"] = "2"
    a_v2["embedded_optional"] = _embedded("opt")
    (store.active_path / "a@v2.json").write_text(json.dumps(a_v2))
    assert _operations_by_path(project, store.name) == {
        ".": "update",
        "embedded_required": "create",
        "embedded_optional": "create",
        "embedded_sequence[name=x]": "update",
        "embedded_sequence[name=y]": "create",
    }

    # Third version: remove y, leave everything else untouched.
    # The slice is updated;
    # x remains changed as it has multiple different versions
    a_v3 = copy.deepcopy(a_v2)
    a_v3["embedded_sequence"] = a_v3["embedded_sequence"][:1]
    (store.active_path / "a@v3.json").write_text(json.dumps(a_v3))
    assert _operations_by_path(project, store.name) == {
        ".": "update",
        "embedded_required": "create",
        "embedded_optional": "create",
        "embedded_sequence[name=x]": "update",
        "embedded_sequence[name=y]": "delete",
    }


def test_update_operation_propagates_through_embedded_tree(
    project: Project, tmp_path: pathlib.Path
) -> None:
    """
    A change deep inside an embedded slice marks the whole chain of parent
    elements as updated, while unaffected sibling elements stay created.
    """
    store = SliceStore(
        name="test_deep",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    # The empty store unrolls to nothing (and the active folder gets created).
    assert _operations_by_path(project, store.name) == {}

    a_v1 = {
        "name": "a",
        "description": None,
        "unique_id": None,
        "embedded_required": _embedded("req", recursive_slice=[_embedded("leaf", "1")]),
        "embedded_optional": None,
        "embedded_sequence": [_embedded("sibling")],
    }
    (store.active_path / "a@v1.json").write_text(json.dumps(a_v1))
    assert _operations_by_path(project, store.name) == {
        ".": "create",
        "embedded_required": "create",
        "embedded_required.recursive_slice[name=leaf]": "create",
        "embedded_sequence[name=sibling]": "create",
    }

    # Change a leaf deep inside embedded_required.  The change bubbles up to
    # embedded_required and the slice itself, but the sibling stays a creation.
    a_v2 = copy.deepcopy(a_v1)
    a_v2["embedded_required"]["recursive_slice"][0]["description"] = "2"
    (store.active_path / "a@v2.json").write_text(json.dumps(a_v2))
    assert _operations_by_path(project, store.name) == {
        ".": "update",
        "embedded_required": "update",
        "embedded_required.recursive_slice[name=leaf]": "update",
        "embedded_sequence[name=sibling]": "create",
    }


def test_update_operation_ignores_deletions_carried_from_older_versions(
    project: Project, tmp_path: pathlib.Path
) -> None:
    """
    Deletions from versions older than the one immediately preceding the
    current one keep being emitted (so the deleted elements stay purged), but
    they must not, on their own, make their unchanged parent look updated: an
    element is only updated when its content changed since the previous
    version.
    """
    store = SliceStore(
        name="test_carried",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    # The empty store unrolls to nothing (and the active folder gets created).
    assert _operations_by_path(project, store.name) == {}

    # v1: embedded_required holds two nested slices, "keep" and "drop".
    a_v1 = {
        "name": "a",
        "description": "v1",
        "unique_id": None,
        "embedded_required": _embedded(
            "req", recursive_slice=[_embedded("keep"), _embedded("drop")]
        ),
        "embedded_optional": None,
        "embedded_sequence": [],
    }
    (store.active_path / "a@v1.json").write_text(json.dumps(a_v1))

    # v2: "drop" is removed, so embedded_required changed and is updated.
    a_v2 = copy.deepcopy(a_v1)
    a_v2["embedded_required"]["recursive_slice"] = [_embedded("keep")]
    (store.active_path / "a@v2.json").write_text(json.dumps(a_v2))
    assert _operations_by_path(project, store.name) == {
        ".": "update",
        "embedded_required": "update",
        "embedded_required.recursive_slice[name=keep]": "create",
        "embedded_required.recursive_slice[name=drop]": "delete",
    }

    # v3: only the root changes.  The deletion of "drop" is carried forward
    # (still emitted as a delete), but embedded_required did not change since
    # v2 and must stay an update.
    a_v3 = copy.deepcopy(a_v2)
    a_v3["description"] = "v3"
    (store.active_path / "a@v3.json").write_text(json.dumps(a_v3))
    assert _operations_by_path(project, store.name) == {
        ".": "update",
        "embedded_required": "update",
        "embedded_required.recursive_slice[name=keep]": "create",
        "embedded_required.recursive_slice[name=drop]": "delete",
    }


def test_delete_embedded_entities(project: Project, tmp_path: pathlib.Path) -> None:
    """
    Test the unrolling behavior when an embedded slice is being removed.
    """
    # Define a basic store
    store = SliceStore(
        name="test3",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    model = """
        import git_ops
        import git_ops::processors
        import unittest

        unittest::Resource(
            name="test3",
            desired_value=std::json_dumps(
                [
                    slice["attributes"]
                    for slice in git_ops::unroll_slices("test3")
                ]
            )
        )
    """

    def desired_state_value() -> object:
        project.compile(model, no_dedent=False)
        resource = project.get_resource("unittest::Resource")
        assert resource is not None
        return json.loads(resource.desired_value)

    # Empty store
    assert desired_state_value() == []

    # Add a first slice to the store
    a = store.active_path / "a@v1.json"
    a_val = {
        "name": "a",
        "description": None,
        "unique_id": None,
        "embedded_required": {
            "name": "a",
            "description": None,
            "unique_id": None,
            "recursive_slice": [
                {
                    "name": "a",
                    "description": None,
                    "unique_id": None,
                    "recursive_slice": [],
                },
            ],
        },
        "embedded_optional": {
            "name": "a",
            "description": None,
            "unique_id": None,
            "recursive_slice": [
                {
                    "name": "a",
                    "description": None,
                    "unique_id": None,
                    "recursive_slice": [],
                },
            ],
        },
        "embedded_sequence": [
            {
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            }
        ],
    }
    a.write_text(json.dumps(a_val))
    assert desired_state_value() == [
        {
            "operation": "create",
            "path": ".",
            "version": 1,
            "slice_store": "test3",
            "slice_name": "a",
            "name": "a",
            "description": None,
            "unique_id": None,
            "embedded_required": {
                "operation": "create",
                "path": "embedded_required",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "create",
                        "path": "embedded_required.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_optional": {
                "operation": "create",
                "path": "embedded_optional",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "create",
                        "path": "embedded_optional.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_sequence": [
                {
                    "operation": "create",
                    "path": "embedded_sequence[name=a]",
                    "name": "a",
                    "description": None,
                    "unique_id": None,
                    "recursive_slice": [
                        {
                            "operation": "create",
                            "path": "embedded_sequence[name=a].recursive_slice[name=a]",
                            "name": "a",
                            "description": None,
                            "unique_id": None,
                            "recursive_slice": [],
                        },
                    ],
                }
            ],
        }
    ]

    # Update the slice, remove the embedded optional entity
    a_v2 = store.active_path / "a@v2.json"
    a_v2_val = copy.deepcopy(a_val)
    a_v2_val["embedded_optional"] = None
    a_v2_val["embedded_sequence"] = []
    a_v2.write_text(json.dumps(a_v2_val))

    assert desired_state_value() == [
        {
            "operation": "update",
            "path": ".",
            "version": 2,
            "slice_store": "test3",
            "slice_name": "a",
            "name": "a",
            "description": None,
            "unique_id": None,
            "embedded_required": {
                "operation": "create",
                "path": "embedded_required",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "create",
                        "path": "embedded_required.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_optional": {
                "operation": "delete",
                "path": "embedded_optional",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "delete",
                        "path": "embedded_optional.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_sequence": [
                {
                    "operation": "delete",
                    "path": "embedded_sequence[name=a]",
                    "name": "a",
                    "description": None,
                    "unique_id": None,
                    "recursive_slice": [
                        {
                            "operation": "delete",
                            "path": "embedded_sequence[name=a].recursive_slice[name=a]",
                            "name": "a",
                            "description": None,
                            "unique_id": None,
                            "recursive_slice": [],
                        },
                    ],
                }
            ],
        }
    ]

    # Remove the slice completely
    a_v2 = store.active_path / "a@v2.json"
    a_v2.write_text(json.dumps({}))

    assert desired_state_value() == [
        {
            "operation": "delete",
            "path": ".",
            "version": 2,
            "slice_store": "test3",
            "slice_name": "a",
            "name": "a",
            "description": None,
            "unique_id": None,
            "embedded_required": {
                "operation": "delete",
                "path": "embedded_required",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "delete",
                        "path": "embedded_required.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_optional": {
                "operation": "delete",
                "path": "embedded_optional",
                "name": "a",
                "description": None,
                "unique_id": None,
                "recursive_slice": [
                    {
                        "operation": "delete",
                        "path": "embedded_optional.recursive_slice[name=a]",
                        "name": "a",
                        "description": None,
                        "unique_id": None,
                        "recursive_slice": [],
                    },
                ],
            },
            "embedded_sequence": [
                {
                    "operation": "delete",
                    "path": "embedded_sequence[name=a]",
                    "name": "a",
                    "description": None,
                    "unique_id": None,
                    "recursive_slice": [
                        {
                            "operation": "delete",
                            "path": "embedded_sequence[name=a].recursive_slice[name=a]",
                            "name": "a",
                            "description": None,
                            "unique_id": None,
                            "recursive_slice": [],
                        },
                    ],
                }
            ],
        }
    ]
