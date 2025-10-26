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

from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice


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
