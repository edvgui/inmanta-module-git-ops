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

import inmanta.ast.type as inmanta_type
from inmanta_plugins.git_ops import slice


def test_basics() -> None:
    abc_slice = slice.SliceEntitySchema(
        name="SliceObjectABC",
        keys=tuple(),
        path=["git_ops", "slice"],
        base_entities=[],
        description="""
    Base class for all slice definitions.  This class should be extended
    by any configuration object that is part of any slice.

    :attr keys: The names of the attributes identifying the instances of this entity.
    """,
        embedded_entities=[],
        attributes=[
            slice.SliceEntityAttributeSchema(
                name="operation",
                description=(
                    "The operation attached to this part of the slice.  "
                    "This dictates what to do with the model emitted by this slice (create/update/delete).  "
                    "This value is not a user input, it is inserted into the slice source when the slice store is populated."
                ),
                inmanta_type=inmanta_type.String(),
            ),
            slice.SliceEntityAttributeSchema(
                name="path",
                description=(
                    "The path leading to this slice object, starting from the root of the slice definition.  "
                    "This value should be a valid dict path expression."
                ),
                inmanta_type=inmanta_type.String(),
            ),
        ],
    )

    named_slice = slice.SliceEntitySchema(
        name="NamedSlice",
        keys=["name"],
        path=["example", "slices", "recursive"],
        base_entities=[abc_slice],
        description="\n    Base class for all slices identified with a name.\n    ",
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
    embedded_slice = EmbeddedSlice.entity_schema()
    assert embedded_slice.embedded_entities[0].entity is embedded_slice

    assert Slice.entity_schema() == slice.SliceEntitySchema(
        name="Slice",
        description="\n    Main slice.\n    ",
        keys=["name"],
        path=["example", "slices", "recursive"],
        base_entities=[named_slice, abc_slice],
        embedded_entities=[
            slice.SliceEntityRelationSchema(
                name="embedded_required",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="EmbeddedRequired",
                    description="\n    Embedded slice that is required.\n    ",
                    keys=["name"],
                    path=["example", "slices", "recursive"],
                    base_entities=[embedded_slice],
                    attributes=[],
                    embedded_entities=[],
                ),
                cardinality_min=1,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_optional",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="EmbeddedOptional",
                    description="\n    Embedded slice that is optional.\n    ",
                    keys=["name"],
                    path=["example", "slices", "recursive"],
                    base_entities=[embedded_slice],
                    attributes=[],
                    embedded_entities=[],
                ),
                cardinality_min=0,
                cardinality_max=1,
            ),
            slice.SliceEntityRelationSchema(
                name="embedded_sequence",
                description=None,
                entity=slice.SliceEntitySchema(
                    name="EmbeddedSequence",
                    description="\n    Embedded slice that is part of a sequence.\n    ",
                    keys=["name"],
                    path=["example", "slices", "recursive"],
                    base_entities=[embedded_slice],
                    attributes=[],
                    embedded_entities=[],
                ),
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
