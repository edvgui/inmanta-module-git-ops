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

from collections.abc import Sequence

import pydantic
from inmanta_plugins.example.slices.fs import File, RootFolder
from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice
from inmanta_plugins.example.slices.simple import Slice as SimpleSlice

from inmanta_git_ops import const
from inmanta_plugins.git_ops import slice


def test_basics() -> None:
    # Generate the entity schema for the recursive example
    schema = Slice.entity_schema()

    assert schema.embedded_slice is False
    assert schema.name == "Slice"
    assert schema.has_many_parents() is False
    assert [a.name for a in schema.attributes] == ["unique_id"]
    assert [a.name for a in schema.all_attributes()] == [
        "operation",
        "path",
        "version",
        "slice_store",
        "slice_name",
        "name",
        "description",
        "unique_id",
    ]
    assert [r.name for r in schema.embedded_entities] == [
        "embedded_required",
        "embedded_optional",
        "embedded_sequence",
    ]
    assert [r.name for r in schema.all_relations()] == [
        "embedded_required",
        "embedded_optional",
        "embedded_sequence",
    ]

    # The top-level slice should not have any parent
    assert [p.name for p in schema.parent_entities] == []

    # The top-level slice should extend the SliceObjectABC
    assert [b.name for b in schema.base_entities] == ["NamedSlice", "SliceObjectABC"]

    embedded_schema = EmbeddedSlice.entity_schema()

    assert embedded_schema.embedded_slice is True
    assert embedded_schema.name == "EmbeddedSlice"
    assert embedded_schema.has_many_parents() is True
    assert [a.name for a in embedded_schema.attributes] == ["unique_id"]
    assert [a.name for a in embedded_schema.all_attributes()] == [
        "operation",
        "path",
        "name",
        "description",
        "unique_id",
    ]
    assert [r.name for r in embedded_schema.embedded_entities] == ["recursive_slice"]
    assert [r.name for r in embedded_schema.all_relations()] == ["recursive_slice"]

    # The embedded slice should have some parents
    assert [p.name for p in embedded_schema.parent_entities] == [
        "recursive_slice",
        "embedded_required",
        "embedded_optional",
        "embedded_sequence",
    ]
    assert [p.name for p in embedded_schema.all_parents()] == [
        "recursive_slice",
        "embedded_required",
        "embedded_optional",
        "embedded_sequence",
    ]

    # The embedded slice should extend the EmbeddedSliceObjectABC
    assert [b.name for b in embedded_schema.base_entities] == ["NamedSlice"]


def test_scaffold() -> None:
    # The scaffold of a slice contains all its properties (including the
    # inherited ones): the required ones with a placeholder value, the
    # others pre-filled with their default value
    assert RootFolder.scaffold() == {
        "name": const.SLICE_PLACEHOLDER,
        "root": const.SLICE_PLACEHOLDER,
        "permissions": "770",
        "owner": None,
        "group": None,
        "type": "folder",
        "content": [],
    }
    assert SimpleSlice.scaffold() == {
        "name": const.SLICE_PLACEHOLDER,
        "description": None,
        "unique_id": None,
        "some_number": 0.0,
        "some_flag": False,
        "some_list": [],
        "some_dict": {},
    }

    # Model-only attributes (such as previous_content) are not part of the
    # scaffold, as they are not part of the slice source files
    assert File.scaffold() == {
        "name": const.SLICE_PLACEHOLDER,
        "permissions": "770",
        "owner": None,
        "group": None,
        "type": "file",
        "content": "",
    }

    # Mandatory embedded relations are scaffolded recursively
    assert Slice.scaffold() == {
        "name": const.SLICE_PLACEHOLDER,
        "description": None,
        "unique_id": None,
        "embedded_required": {
            "name": const.SLICE_PLACEHOLDER,
            "description": None,
            "unique_id": None,
            "recursive_slice": [],
        },
        "embedded_optional": None,
        "embedded_sequence": [],
    }


def test_scaffold_embedded_defaults() -> None:
    class Container(slice.EmbeddedSliceObjectABC):
        image: str
        cpus: float = 1.0

    class Service(slice.SliceObjectABC):
        name: str
        container: Container = pydantic.Field(default_factory=Container)
        replicas: Sequence[Container] = pydantic.Field(
            default_factory=lambda: [Container(image="alpine")]
        )
        invalid: Sequence[Container] = pydantic.Field(
            default_factory=lambda: [Container()]
        )

    assert Service.scaffold() == {
        "name": const.SLICE_PLACEHOLDER,
        # A mandatory embedded relation is scaffolded recursively even when
        # the field has a default: the factory can not construct the embedded
        # object as it has required properties of its own
        "container": {
            "image": const.SLICE_PLACEHOLDER,
            "cpus": 1.0,
        },
        # Embedded objects in a default value are serialized like the slice
        # files, without the model-only attributes
        "replicas": [{"image": "alpine", "cpus": 1.0}],
        # A default that can not be constructed falls back to the placeholder
        "invalid": const.SLICE_PLACEHOLDER,
    }
