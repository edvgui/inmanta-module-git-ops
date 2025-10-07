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
import logging
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pydantic
import typing_inspect

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

    # None to None
    if python_type is type(None) or python_type is None:
        return inmanta_type.Null()

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

    # Primitive types
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
    name: str
    description: str | None
    entity: "SliceEntitySchema"
    cardinality_min: int = 0
    cardinality_max: int | None = None


@dataclass(kw_only=True)
class SliceEntityAttributeSchema:
    name: str
    description: str | None
    inmanta_type: inmanta_type.Type


@dataclass(kw_only=True)
class SliceEntitySchema:
    name: str
    keys: Sequence[str]
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


class SliceObjectABC(pydantic.BaseModel):
    keys: typing.ClassVar[Sequence[str]] = tuple()

    operation: str
    path: str

    @classmethod
    def entity_schema(cls) -> SliceEntitySchema:
        cached_attribute = f"_{cls.__name__}__entity_schema__"
        if hasattr(cls, cached_attribute):
            return typing.cast(SliceEntitySchema, getattr(cls, cached_attribute))

        embedded_entities: list[SliceEntityRelationSchema] = []
        attributes: list[SliceEntityAttributeSchema] = []

        # Handle recursive type definition by setting up the schema
        # cache before exploring any of the relations
        entity_schema = SliceEntitySchema(
            name=cls.__name__,
            keys=cls.keys,
            base_entities=[
                base_class.entity_schema()
                for base_class in cls.__bases__
                if issubclass(base_class, SliceObjectABC)
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
                LOGGER.warning(
                    "%s.%s doesn't have any type annotation",
                    str(cls),
                    attribute,
                )
                continue

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

            # Required relation
            if issubclass(python_type, SliceObjectABC):
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

            # Optional relation
            with contextlib.suppress(ValueError):
                optional = get_optional_type(python_type)
                if issubclass(optional, SliceObjectABC):
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

            # Relation
            if (
                typing_inspect.is_generic_type(python_type)
                and (origin := typing.get_origin(python_type)) is not None
                and origin in [Sequence, list, typing.Sequence]
                and (args := typing.get_args(python_type)) is not None
            ):
                if issubclass(args[0], SliceObjectABC):
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

            # Couldn't parse the attribute, log a warning and continue
            LOGGER.warning(
                "%s.%s has an unsupported type annotation: %s",
                str(cls),
                attribute,
                str(python_type),
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
