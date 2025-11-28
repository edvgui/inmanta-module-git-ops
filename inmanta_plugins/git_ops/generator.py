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

import functools
import importlib
import pathlib
from collections.abc import Sequence

from inmanta_module_factory.builder import InmantaModuleBuilder
from inmanta_module_factory.helpers import utils
from inmanta_module_factory.inmanta import (
    Attribute,
    Entity,
    EntityField,
    EntityRelation,
    Implement,
    Implementation,
    Index,
    InmantaAdvancedType,
    InmantaBooleanType,
    InmantaDictType,
    InmantaFloatType,
    InmantaIntegerType,
    InmantaListType,
    InmantaStringType,
    InmantaType,
)
from inmanta_module_factory.inmanta.modules import std

from inmanta.ast.type import (
    Bool,
    Dict,
    Float,
    Integer,
    List,
    NullableType,
    String,
    Type,
    TypedList,
)
from inmanta.module import Module, ModuleV2, ModuleV2Source
from inmanta_plugins.git_ops import slice

# Cache entities to support recursive schema generation
ENTITIES: dict[Sequence[str], Entity] = {}


@functools.lru_cache
def get_module(module: str) -> Module:
    """
    Get the module object for the module with the given name, installed
    installed in the current virtual environment.

    :param module: The name of the module.
    """
    # Resolve the module path by importing the module's plugin
    # and locating the source file
    python_module = importlib.import_module(f"inmanta_plugins.{module}")
    if python_module.__file__ is None:
        raise RuntimeError(f"Failed to resolve path of module {module}")

    # Path to the plugins directory
    plugins_path = pathlib.Path(python_module.__file__).parent

    if (plugins_path / "setup.cfg").exists():
        # Non-editable install
        module = ModuleV2.from_path(str(plugins_path))
    else:
        # Editable install
        module = ModuleV2Source.from_path(
            None,
            module,
            str(plugins_path.parent.parent),
        )

    if module is None:
        raise RuntimeError(f"No module at path {plugins_path}")

    return module


@functools.lru_cache
def get_module_builder(module: str) -> InmantaModuleBuilder:
    """
    Construct and cache the module builder for the given module.  The
    module must be installed in the current venv.

    :param module: The name of the module.
    """
    return InmantaModuleBuilder.from_existing_module(get_module(module))


def long_description(
    description: str | None, *, max_len: int = 90, indent: str = ""
) -> str | None:
    """
    Split the description into multiple lines (if it doesn't contain any
    newline characters already) to keep lines of maximum n characters.

    :param description: The original description
    :param max_len: The maximum length the description can have
    :param indent: The indentation to add to each newline (after from the initial one)
    """
    if description is None:
        return None

    if "\n" in description:
        return description

    if len(description) < max_len:
        return description

    words = description.split(" ")
    formatted_description: list[str] = [""]
    for word in words:
        if len(formatted_description[-1]) + len(word) > max_len:
            formatted_description.append(indent + word)
        elif formatted_description[-1]:
            formatted_description[-1] += " " + word
        else:
            formatted_description[-1] += word

    return "\n".join(formatted_description)


def get_attribute_type(inmanta_type: Type) -> InmantaType:
    """
    Map a type of the inmanta dsl to the corresponding generator equivalent.
    """
    match inmanta_type:
        case String():
            return InmantaStringType
        case Integer():
            return InmantaIntegerType
        case Float():
            return InmantaFloatType
        case Bool():
            return InmantaBooleanType
        case Dict():
            return InmantaDictType
        case TypedList():
            return InmantaListType(get_attribute_type(inmanta_type.element_type))
        case List():
            return InmantaAdvancedType("list")
        case NullableType():
            return get_attribute_type(inmanta_type.element_type)
        case _:
            raise ValueError(f"Unsupported attribute type: {inmanta_type}")


def get_attribute(
    schema: slice.SliceEntityAttributeSchema,
    *,
    entity: Entity,
) -> Attribute:
    """
    Generate the attribute matching the input schema.

    :param schema: The schema defining the attribute type and description.
    :param builder: The builder in which the entity to which this attribute
        belongs will be added.
    """
    return Attribute(
        name=schema.name,
        inmanta_type=get_attribute_type(schema.inmanta_type),
        optional=isinstance(schema.inmanta_type, NullableType),
        description=long_description(schema.description, max_len=70, indent=" " * 4),
        entity=entity,
    )


def get_relation(
    schema: slice.SliceEntityRelationSchema,
    *,
    parent: Entity,
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
    builder = get_module_builder(schema.entity.path[0])

    parent_relation = EntityRelation(
        name="parent",
        path=schema.entity.path,
        cardinality=(1, 1),
        description="Relation to parent",
    )

    if schema.entity.has_many_parents():
        base = get_entity(
            schema=schema.entity,
            parent_relation=None,
        )
        embedded_entity = Entity(
            name=parent.name + utils.inmanta_entity_name(schema.name),
            path=parent.path,
            parents=[base],
            description=(
                "This entity has been generated because it's base entity:\n\n"
                f"    {base.full_path_string}\n\n"
                "has multiple parent.  Or in other words, multiple entities\n"
                "have a relation to this base entity, making it impossible\n"
                "to define a unique parent relation."
            ),
            force_attribute_doc=False,
            sort_attributes=False,
        )

        builder.add_module_element(embedded_entity)

        key_fields: dict[str, EntityField] = {}

        if parent_relation is not None:
            key_fields[parent_relation.name] = parent_relation

        for field in embedded_entity.all_fields():
            if field.name in schema.entity.keys:
                key_fields[field.name] = field

        builder.add_module_element(
            Index(
                path=embedded_entity.path,
                entity=embedded_entity,
                fields=key_fields.values(),
            )
        )

        # Add a basic implement statement
        builder.add_module_element(
            Implement(
                path=embedded_entity.path,
                implementation=None,
                entity=embedded_entity,
                using_parents=True,
            )
        )
    else:
        embedded_entity = get_entity(
            schema=schema.entity,
            parent_relation=parent_relation,
        )

    parent_relation.attach_entity(embedded_entity)
    embedded_entity.attach_field(parent_relation)

    return EntityRelation(
        name=schema.name,
        path=parent.path,
        cardinality=(schema.cardinality_min, schema.cardinality_max),
        description=long_description(schema.description),
        peer=parent_relation,
        entity=parent,
    )


def get_entity(
    schema: slice.SliceEntitySchema,
    *,
    slice_root: bool = False,
    parent_relation: EntityRelation | None = None,
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

    builder = get_module_builder(entity_path[0])

    # Emit the entity
    entity = Entity(
        name=schema.name,
        path=schema.path,
        parents=[
            get_entity(
                schema=parent,
            )
            for parent in schema.base_entities
        ]
        + [std.entity],
        description=long_description(schema.description),
        force_attribute_doc=False,
        sort_attributes=False,
    )
    ENTITIES[entity_path] = entity
    builder.add_module_element(entity)

    # Go over all the attributes and relations
    for attribute in schema.attributes:
        get_attribute(attribute, entity=entity)

    for relation in schema.embedded_entities:
        builder.add_module_element(
            get_relation(
                schema=relation,
                parent=entity,
            )
        )

    # Generate an index
    if slice_root or parent_relation is not None:
        key_fields: dict[str, EntityField] = {}

        if parent_relation is not None:
            key_fields[parent_relation.name] = parent_relation

        for field in entity.all_fields():
            if field.name in schema.keys:
                key_fields[field.name] = field

        builder.add_module_element(
            Index(
                path=entity.path,
                entity=entity,
                fields=key_fields.values(),
            )
        )

    # Add a basic implement statement
    builder.add_module_element(
        Implement(
            path=entity.path,
            implementation=None,
            entity=entity,
            using_parents=True,
            implementations=[std.none],
        )
    )

    return entity


# Pre-populate the entities of the git_ops module
SLICE_OBJECT_ABC = get_entity(slice.SliceObjectABC.entity_schema())
EMBEDDED_SLICE_OBJECT_ABC = get_entity(slice.EmbeddedSliceObjectABC.entity_schema())

# Add a resources relation to the embedded slice object
get_module_builder("git_ops").add_module_element(
    EntityRelation(
        entity=EMBEDDED_SLICE_OBJECT_ABC,
        name="resources",
        path=["git_ops", "slice"],
        cardinality=(0, None),
        description="""A list of all the resources that have been emitted by refining this embedded
slice entity.  This has no current use.
""",
        peer=EntityRelation(
            name="",
            path=["git_ops", "slice"],
            cardinality=(1, 1),
            entity=std.resource,
        ),
    )
)
get_module_builder("git_ops").add_module_element(
    EntityRelation(
        entity=EMBEDDED_SLICE_OBJECT_ABC,
        name="owned_resources",
        path=["git_ops", "slice"],
        cardinality=(0, None),
        description="""A list of all the resources that have been emitted by refining this embedded
slice entity.  This has no current use.
""",
        peer=EntityRelation(
            name="",
            path=["git_ops", "slice"],
            cardinality=(1, 1),
            entity=std.resource,
        ),
    )
)

# Add an implementation that wires the resources of an embedded entity
# into the resources of its parent
PARENT_RELATIONS_IMPLEMENTATION = Implementation(
    name="parent_relations",
    path=["git_ops", "slice"],
    entity=EMBEDDED_SLICE_OBJECT_ABC,
    content=(
        "self.parent.resources += self.resources\n"
        "self.parent.owned_resources += self.owned_resources"
    ),
    description="Attach the resources to the parent resources.",
)
get_module_builder("git_ops").add_module_element(PARENT_RELATIONS_IMPLEMENTATION)
