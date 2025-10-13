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

import contextlib
import inspect
import logging
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pydantic
import typing_inspect
from pydantic.json_schema import SkipJsonSchema

import inmanta.ast.type as inmanta_type

LOGGER = logging.getLogger(__name__)


def get_optional_type(python_type: type[object]) -> type[object]:
    """
    If the input type is a union of type A and None, return type A.
    Otherwise raise a ValueError.

    :param python_type: The type which we expect to be an optional.
    """
    if not typing_inspect.is_union_type(python_type):
        raise ValueError(f"Type {python_type} is not optional (union)")

    if not typing_inspect.is_optional_type(python_type):
        raise ValueError(f"Type {python_type} is not optional (nullable)")

    other_types = [
        tt
        for tt in typing.get_args(python_type)
        if not typing_inspect.is_optional_type(tt)
    ]
    if len(other_types) == 0:
        raise ValueError(f"Type {python_type} is not optional (null)")

    if len(other_types) == 1:
        return other_types[0]

    raise ValueError(f"Type {python_type} is not a supported optional")


def to_inmanta_type(python_type: type[object]) -> inmanta_type.Type:
    """
    Try to convert a python type annotation to an Inmanta DSL type annotation.
    Only the conversion to inmanta primitive types is supported.
    If the conversion is not possible, raise a ValueError.

    :param python_type: The python type annotation.
    """
    # Resolve aliases
    if isinstance(python_type, typing.TypeAliasType):
        return to_inmanta_type(python_type.__value__)

    # Optional type
    if typing_inspect.is_union_type(python_type) and typing_inspect.is_optional_type(
        python_type
    ):
        return inmanta_type.NullableType(
            to_inmanta_type(get_optional_type(python_type))
        )

    # Lists and dicts
    if typing_inspect.is_generic_type(python_type):
        origin = typing.get_origin(python_type)
        if origin in [Mapping, dict, typing.Mapping]:
            return inmanta_type.TypedDict(inmanta_type.Any())
        elif origin in [Sequence, list, typing.Sequence]:
            args = typing.get_args(python_type)
            if not args:
                return inmanta_type.List()
            return inmanta_type.TypedList(to_inmanta_type(args[0]))
        else:
            raise ValueError(f"Can not handle type {python_type} (generic)")

    # Basic types
    if python_type is list:
        return inmanta_type.List()

    if python_type is dict:
        return inmanta_type.Dict()

    if python_type is str:
        return inmanta_type.String()

    if python_type is bool:
        return inmanta_type.Bool()

    if python_type is float:
        return inmanta_type.Float()

    if python_type is int:
        return inmanta_type.Integer()

    raise ValueError(f"Can not handle type {python_type}")


@dataclass(kw_only=True)
class SliceEntityRelationSchema:
    """
    Schema of a relation connection a slice entity to another
    embedded slice entity.

    :attr name: The name of the relation, matching the attribute
        name in the python definition.
    :attr description: The description of the python attribute, if
        there is any.
    :attr entity: The embedded entity's schema.
    :attr cardinality_min: The minimal amount of embedded entity
        instances which are required to be attached to the parent.
    :attr cardinality_max: The maximal amount of embedded entity
        instances which are required to be attached to the parent.
    """

    name: str
    description: str | None
    entity: "SliceEntitySchema"
    cardinality_min: int = 0
    cardinality_max: int | None = None


@dataclass(kw_only=True)
class SliceEntityAttributeSchema:
    """
    Schema of an attribute of a slice entity.  The difference
    with the relation schema is the nature of the type.  Attributes
    may only contain primitive values, while relations point to
    entities.

    :attr name: The name of the attribute, matching the attribute
        name in the python definition.
    :attr description: The description of the python attribute, if
        there is any.
    :attr inmanta_type: The type of the attribute, translated into
        the inmanta type system.
    """

    name: str
    description: str | None
    inmanta_type: inmanta_type.Type


@dataclass(kw_only=True)
class SliceEntitySchema:
    """
    Schema of an slice entity, with all its attributes and relations.

    :attr name: The name of the entity, matching the class name of the
        python definition.
    :attr keys: A collection of names of attributes of this entity, which
        should be used to identify instances of this entity grouped in the
        same relation.
    :attr base_entities: The entity schema matching the parent classes of
        the class for which this entity schema is emitted.
    :attr description: The description of the python class defining the
        entity, if there is any.
    :attr embedded_entities: A list of relations towards other slice entities.
    :attr attributes: A list of attributes defined on the entity.
    """

    name: str
    keys: Sequence[str]
    path: Sequence[str]
    base_entities: Sequence["SliceEntitySchema"]
    description: str | None
    embedded_entities: Sequence[SliceEntityRelationSchema]
    attributes: Sequence[SliceEntityAttributeSchema]

    def all_attributes(self) -> Sequence[SliceEntityAttributeSchema]:
        """
        Get all of the attributes that can be used by instances of this
        entity.  This includes the attributes defined on this entity and
        the one defined an any of its parents.
        """
        attributes_by_name: dict[str, SliceEntityAttributeSchema] = dict()

        for base_entity in reversed(self.base_entities):
            attributes_by_name.update(
                {attr.name: attr for attr in base_entity.all_attributes()}
            )

        attributes_by_name.update({attr.name: attr for attr in self.attributes})
        return list(attributes_by_name.values())

    def all_relations(self) -> Sequence[SliceEntityRelationSchema]:
        """
        Get all of the relations that can be used by instances of this
        entity.  This includes the relations defined on this entity and
        the one defined an any of its parents.
        """
        relations_by_name: dict[str, SliceEntityRelationSchema] = dict()

        for base_entity in reversed(self.base_entities):
            relations_by_name.update(
                {attr.name: attr for attr in base_entity.all_relations()}
            )

        relations_by_name.update({attr.name: attr for attr in self.embedded_entities})
        return list(relations_by_name.values())


class SliceObjectABC(pydantic.BaseModel):
    """
    Base class for all slice definitions.  This class should be extended
    by any configuration object that is part of any slice.

    :attr keys: The names of the attributes identifying the instances of this entity.
    """

    keys: typing.ClassVar[Sequence[str]] = tuple()

    operation: SkipJsonSchema[str] = pydantic.Field(
        default="create",
        description=(
            "The operation attached to this part of the slice.  "
            "This dictates what to do with the model emitted by this slice (create/update/delete).  "
            "This value is not a user input, it is inserted into the slice source when the slice store is populated."
        ),
        exclude=True,
    )
    path: SkipJsonSchema[str] = pydantic.Field(
        default=".",
        description=(
            "The path leading to this slice object, starting from the root of the slice definition.  "
            "This value should be a valid dict path expression."
        ),
        exclude=True,
    )

    @classmethod
    def entity_schema(cls) -> SliceEntitySchema:
        """
        Emit the schema of the entity corresponding to this slice class.
        This schema can be used to generate the model definition matching
        the python class definition.
        """

        cached_attribute = f"_{cls.__name__}__entity_schema__"
        if hasattr(cls, cached_attribute):
            return typing.cast(SliceEntitySchema, getattr(cls, cached_attribute))

        embedded_entities: list[SliceEntityRelationSchema] = []
        attributes: list[SliceEntityAttributeSchema] = []

        # Validate that the class is defined in an inmanta module
        if not cls.__module__.startswith("inmanta_plugins."):
            raise ValueError(
                f"{cls} is not defined in an inmanta module: {cls.__module__}"
            )

        # Handle recursive type definition by setting up the schema
        # cache before exploring any of the relations
        entity_schema = SliceEntitySchema(
            name=cls.__name__,
            keys=cls.keys,
            path=cls.__module__.split(".")[1:],
            base_entities=[
                base_class.entity_schema()
                for base_class in cls.__bases__
                if inspect.isclass(base_class)
                and issubclass(base_class, SliceObjectABC)
            ],
            description=cls.__doc__,
            embedded_entities=embedded_entities,
            attributes=attributes,
        )
        setattr(cls, cached_attribute, entity_schema)

        for attribute, info in cls.model_fields.items():
            python_type = info.annotation

            if attribute not in cls.__annotations__:
                # This attribute is defined on a parent class
                continue

            if python_type is None:
                # No annotation
                raise ValueError(f"{cls}.{attribute} doesn't have any type annotation")

            # Primitive
            with contextlib.suppress(ValueError):
                # Try to resolve the corresponding inmanta primitive
                # type.  If there is none, skip the attribute
                attributes.append(
                    SliceEntityAttributeSchema(
                        name=attribute,
                        description=info.description,
                        inmanta_type=to_inmanta_type(python_type),
                    ),
                )
                continue

            # Relation
            if (
                typing_inspect.is_generic_type(python_type)
                and (origin := typing.get_origin(python_type)) is not None
                and origin in [Sequence, list, typing.Sequence]
                and (args := typing.get_args(python_type)) is not None
            ):
                if inspect.isclass(args[0]) and issubclass(args[0], SliceObjectABC):
                    embedded_entities.append(
                        SliceEntityRelationSchema(
                            name=attribute,
                            description=info.description,
                            entity=args[0].entity_schema(),
                            cardinality_min=0,
                            cardinality_max=None,
                        )
                    )
                    continue

            # Optional relation
            with contextlib.suppress(ValueError):
                optional = get_optional_type(python_type)
                if inspect.isclass(optional) and issubclass(optional, SliceObjectABC):
                    embedded_entities.append(
                        SliceEntityRelationSchema(
                            name=attribute,
                            description=info.description,
                            entity=optional.entity_schema(),
                            cardinality_min=0,
                            cardinality_max=1,
                        )
                    )
                    continue

            # Required relation
            if inspect.isclass(python_type) and issubclass(python_type, SliceObjectABC):
                embedded_entities.append(
                    SliceEntityRelationSchema(
                        name=attribute,
                        description=info.description,
                        entity=python_type.entity_schema(),
                        cardinality_min=1,
                        cardinality_max=1,
                    )
                )
                continue

            # Couldn't parse the attribute, log a warning and continue
            raise ValueError(
                f"{cls}.{attribute} has an unsupported type annotation: {python_type}"
            )

        # Validate that the keys all match attributes
        attribute_names = [attr.name for attr in entity_schema.all_attributes()]
        missing = set(cls.keys) - set(attribute_names)
        if missing:
            raise ValueError(
                "The keys of a slice object should always match its attributes. "
                f"Some keys of {cls} don't follow this constraint: {missing}"
            )

        return entity_schema
