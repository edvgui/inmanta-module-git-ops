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

from inmanta_module_factory.builder import InmantaModuleBuilder
from inmanta_module_factory.inmanta import (
    Attribute,
    Entity,
    EntityField,
    EntityRelation,
    Implement,
    Index,
)

from inmanta.ast.type import NullableType
from inmanta_plugins.git_ops import slice

# Cache entities to support recursive schema generation
ENTITIES: dict[Sequence[str], Entity] = {}


def get_attribute(
    schema: slice.SliceEntityAttributeSchema,
    *,
    builder: InmantaModuleBuilder,
) -> Attribute:
    """
    Generate the attribute matching the input schema.

    :param schema: The schema defining the attribute type and description.
    :param builder: The builder in which the entity to which this attribute
        belongs will be added.
    """
    return Attribute(
        name=schema.name,
        inmanta_type=(
            schema.inmanta_type.element_type.type_string()
            if isinstance(schema.inmanta_type, NullableType)
            else schema.inmanta_type.type_string()
        ),
        optional=isinstance(schema.inmanta_type, NullableType),
        description=schema.description,
    )


def get_relation(
    schema: slice.SliceEntityRelationSchema,
    *,
    entity: Entity,
    builder: InmantaModuleBuilder,
) -> EntityRelation:
    """
    Generate the entity relation equivalent to the input schema.  The reverse
    relation is always set and named "_parent".  This function also delegates
    the creation of the target entity to the get_entity function.

    :param schema: The schema of the relation.
    :param entity: The entity that this relation attaches to.
    :param builder: The module builder in which the target entity should be
        added.
    """
    parent_relation = EntityRelation(
        name="_parent",
        path=schema.entity.path,
        cardinality=(1, 1),
        description="Relation to parent",
    )
    get_entity(
        schema=schema.entity,
        builder=builder,
        parent_relation=parent_relation,
    )

    return EntityRelation(
        name=schema.name,
        path=entity.path,
        cardinality=(schema.cardinality_min, schema.cardinality_max),
        description=schema.description,
        peer=parent_relation,
        entity=entity,
    )


def get_entity(
    schema: slice.SliceEntitySchema,
    *,
    parent_relation: EntityRelation | None = None,
    builder: InmantaModuleBuilder,
) -> Entity:
    """
    Translate the input entity schema into an equivalent entity definition
    and add it to the inmanta module builder.  The entity should be use the
    class name as name, and use the class path inside a module as submodule
    path.

    :param schema: The schema of the slice object class.
    :param parent_relation: When set, this object represents the relation
        that attaches this entity to a parent in the slice tree.  We should
        attach the relation to the entity, and use it in the index of the
        entity.
    :param builder: The inmanta module builder in which the entity should
        be added.
    """
    entity_path = tuple(schema.path + [schema.name])
    if entity_path in ENTITIES:
        return ENTITIES[entity_path]

    # Emit the entity
    entity = Entity(
        name=schema.name,
        path=schema.path,
        parents=[
            get_entity(
                schema=parent,
                builder=builder,
            )
            for parent in schema.base_entities
        ],
        description=schema.description,
    )
    ENTITIES[entity_path] = entity
    builder.add_module_element(entity)

    # Collect all the fields that should be part of the index
    index_fields: list[EntityField] = []
    if parent_relation is not None:
        entity.attach_field(parent_relation)
        index_fields.append(parent_relation)

    # Go over all the attributes and relations
    for attribute in schema.attributes:
        a = get_attribute(attribute, builder=builder)

        if a.name in schema.keys:
            index_fields.append(a)

        entity.attach_field(a)

    for relation in schema.embedded_entities:
        builder.add_module_element(
            get_relation(
                schema=relation,
                builder=builder,
                entity=entity,
            )
        )

    # Generate an index
    if index_fields:
        builder.add_module_element(
            Index(
                path=entity.path,
                entity=entity,
                fields=index_fields,
            )
        )

    # Add a basic implement statement
    builder.add_module_element(
        Implement(
            path=entity.path,
            implementation=None,
            entity=entity,
            using_parents=True,
        )
    )

    return entity
