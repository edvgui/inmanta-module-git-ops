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

import typing
from collections.abc import Sequence

import inmanta.ast.type as inmanta_type
from inmanta_plugins.git_ops import slice


# Test base classes
class NamedSlice(slice.SliceObjectABC):
    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str
    description: str | None


class TestEmbeddedSlice(NamedSlice, slice.SliceObjectABC):
    unique_id: int | None = None

    # Test recursion
    recursive_slice: Sequence["TestEmbeddedSlice"] = []


class TestSlice(NamedSlice, slice.SliceObjectABC):
    unique_id: int | None = None

    embedded_required: TestEmbeddedSlice
    embedded_optional: TestEmbeddedSlice | None = None
    embedded_sequence: Sequence[TestEmbeddedSlice] = []


def test_basics() -> None:
    abc_slice = slice.SliceEntitySchema(
        name="SliceObjectABC",
        keys=tuple(),
        base_entities=[],
        description=None,
        embedded_entities=[],
        attributes=[
            slice.SliceEntityAttributeSchema(
                name="operation",
                description=None,
                inmanta_type=inmanta_type.String(),
            ),
            slice.SliceEntityAttributeSchema(
                name="path",
                description=None,
                inmanta_type=inmanta_type.String(),
            ),
        ],
    )

    named_slice = slice.SliceEntitySchema(
        name="NamedSlice",
        keys=["name"],
        base_entities=[abc_slice],
        description=None,
        embedded_entities=[],
        attributes=[
            slice.SliceEntityAttributeSchema(
                name="name",
                description=None,
                inmanta_type=inmanta_type.String(),
            ),
            slice.SliceEntityAttributeSchema(
                name="description",
                description=None,
                inmanta_type=inmanta_type.NullableType(inmanta_type.String()),
            ),
        ],
    )

    # Hack infinite recursion equality by using the same object instead of
    # and equivalent one.  "is" check doesn't need to recurse, while "eq" does.
    embedded_slice = TestEmbeddedSlice.entity_schema()
    assert embedded_slice.embedded_entities[0].entity is embedded_slice

    assert TestSlice.entity_schema() == slice.SliceEntitySchema(
        name="TestSlice",
        description=None,
        keys=["name"],
        base_entities=[named_slice, abc_slice],
        embedded_entities=[
            slice.SliceEntityRelationSchema(
                name="embedded_required",
                description=None,
                entity=embedded_slice,
                cardinality_min=1,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_optional",
                description=None,
                entity=embedded_slice,
                cardinality_min=0,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_sequence",
                description=None,
                entity=embedded_slice,
                cardinality_min=0,
                cardinality_max=None,
            ),
        ],
        attributes=[
            slice.SliceEntityAttributeSchema(
                name="unique_id",
                description=None,
                inmanta_type=inmanta_type.NullableType(inmanta_type.Integer()),
            ),
        ],
    )
