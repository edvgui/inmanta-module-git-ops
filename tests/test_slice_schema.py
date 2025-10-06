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


class TestEmbeddedSlice(slice.SliceObjectABC):
    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str
    unique_id: int | None = None
    description: str


class TestSlice(slice.SliceObjectABC):
    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str
    unique_id: int | None = None
    description: str

    embedded_required: TestEmbeddedSlice
    embedded_optional: TestEmbeddedSlice | None = None
    embedded_sequence: Sequence[TestEmbeddedSlice] = []


def test_basics() -> None:
    assert TestSlice.entity_schema() == slice.SliceEntitySchema(
        name="TestSlice",
        description=None,
        keys=["name"],
        base_entities=[],
        embedded_entities=[
            slice.SliceEntityRelationSchema(
                name="embedded_required",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="TestEmbeddedSlice",
                    keys=["name"],
                    base_entities=[],
                    description=None,
                    embedded_entities=[],
                    attributes=[
                        slice.SliceEntityAttributeSchema(
                            name="name",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="unique_id",
                            description=None,
                            inmanta_type=inmanta_type.NullableType(
                                inmanta_type.Integer()
                            ),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="description",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                    ],
                ),
                cardinality_min=1,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_optional",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="TestEmbeddedSlice",
                    keys=["name"],
                    base_entities=[],
                    description=None,
                    embedded_entities=[],
                    attributes=[
                        slice.SliceEntityAttributeSchema(
                            name="name",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="unique_id",
                            description=None,
                            inmanta_type=inmanta_type.NullableType(
                                inmanta_type.Integer()
                            ),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="description",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                    ],
                ),
                cardinality_min=0,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_sequence",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="TestEmbeddedSlice",
                    keys=["name"],
                    base_entities=[],
                    description=None,
                    embedded_entities=[],
                    attributes=[
                        slice.SliceEntityAttributeSchema(
                            name="name",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="unique_id",
                            description=None,
                            inmanta_type=inmanta_type.NullableType(
                                inmanta_type.Integer()
                            ),
                        ),
                        slice.SliceEntityAttributeSchema(
                            name="description",
                            description=None,
                            inmanta_type=inmanta_type.String(),
                        ),
                    ],
                ),
                cardinality_min=0,
                cardinality_max=None,
            ),
        ],
        attributes=[
            slice.SliceEntityAttributeSchema(
                name="name",
                description=None,
                inmanta_type=inmanta_type.String(),
            ),
            slice.SliceEntityAttributeSchema(
                name="unique_id",
                description=None,
                inmanta_type=inmanta_type.NullableType(inmanta_type.Integer()),
            ),
            slice.SliceEntityAttributeSchema(
                name="description",
                description=None,
                inmanta_type=inmanta_type.String(),
            ),
        ],
    )
