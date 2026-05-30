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
import itertools
import logging
import sys
import textwrap
import typing
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import pydantic
import typing_inspect
from pydantic.json_schema import SkipJsonSchema

import inmanta.ast.type as inmanta_type

LOGGER = logging.getLogger(__name__)

SLICE_UPDATE = ContextVar("SLICE_UPDATE", default=False)


def slice_update(value: object) -> bool:
    """
    Assign this callable to the exclude_if attribute of fields that
    should be present in the model but not in the slice source files.
    The value of this function will always return False, except when
    serializing slices before writing them to file.

    .. code-block:: python

        class Example(SliceObjectABC):
            mode_attr: str = pydantic.Field(
                default="a",
                exclude_if=slice_update,
            )


    :param value: Whatever value is present in the attribute.
    """
    return SLICE_UPDATE.get()


@contextmanager
def exclude_model_values() -> Generator[None, None, None]:
    """
    Inside this context, serialization of slice objects will ignore
    model_only attributes.  This allows to define attributes that
    should be generated in the model, exported during the unroll, but
    not saved to the slice files (as they have no additional values).
    """
    token = SLICE_UPDATE.set(True)
    yield
    SLICE_UPDATE.reset(token)


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

    # Literal type: the literal values themselves carry the type, so we
    # translate it to the inmanta type of the underlying primitive value(s).
    if typing_inspect.is_literal_type(python_type):
        value_types = {type(value) for value in typing.get_args(python_type)}
        if len(value_types) != 1:
            raise ValueError(
                f"Can not handle literal type {python_type} with values of "
                f"mixed types {value_types}"
            )
        return to_inmanta_type(value_types.pop())

    # Lists and dicts
    if typing_inspect.is_generic_type(python_type):
        origin = typing.get_origin(python_type)
        if origin in [Mapping, dict, typing.Mapping]:
            return inmanta_type.Dict()
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


# Cache for the synthetic entity schemas representing discriminated unions.
# Keyed by (module name, union name) to support recursive type definitions.
_UNION_SCHEMA_CACHE: dict[tuple[str, str], "SliceEntitySchema"] = {}


def resolve_forward_reference(
    annotation: object, owner_cls: type
) -> tuple[object, str | None]:
    """
    Resolve a (possibly) forward referenced annotation against the module in
    which the owner class is defined.  Return the resolved value together with
    the name of the reference when it was a forward reference.

    :param annotation: The annotation to resolve, either a concrete value, a
        string or a typing.ForwardRef.
    :param owner_cls: The class on which the annotation is defined, used to
        locate the module namespace.
    """
    name: str | None = None
    if isinstance(annotation, str):
        name = annotation
    elif isinstance(annotation, typing.ForwardRef):
        name = annotation.__forward_arg__

    if name is None:
        return annotation, None

    module = sys.modules[owner_cls.__module__]
    return getattr(module, name, None), name


def discriminated_union(
    annotation: object, owner_cls: type, *, fallback_name: str | None
) -> tuple[str, str, Sequence[type]] | None:
    """
    If the given annotation is a discriminated union (a typing.Annotated union
    carrying a pydantic discriminator), return the name of the union, the name
    of the discriminator attribute and the sequence of member classes.
    Otherwise return None.

    :param annotation: The (resolved) annotation to inspect.
    :param owner_cls: The class on which the annotation is defined.
    :param fallback_name: The name to use for the union if it can not be
        derived from a forward reference (e.g. the relation attribute name).
    """
    resolved, name = resolve_forward_reference(annotation, owner_cls)
    if name is None:
        name = fallback_name

    metadata = getattr(resolved, "__metadata__", None)
    if not metadata:
        return None

    discriminator: str | None = None
    for meta in metadata:
        discriminator = getattr(meta, "discriminator", None) or discriminator

    if discriminator is None or name is None:
        return None

    union_type = typing.get_args(resolved)[0]
    members = [
        member
        for member in typing.get_args(union_type)
        if inspect.isclass(member) and issubclass(member, EmbeddedSliceObjectABC)
    ]
    if not members:
        return None

    return name, discriminator, members


def union_schema(
    name: str,
    discriminator: str,
    members: Sequence[type],
    owner_cls: type,
) -> "SliceEntitySchema":
    """
    Build (or return from cache) the synthetic entity schema representing a
    discriminated union.  The union becomes a base entity defining the
    discriminator attribute, and each member is registered as a sub entity
    extending it.

    :param name: The name of the union entity.
    :param discriminator: The name of the discriminator attribute.
    :param members: The member classes of the union.
    :param owner_cls: The class defining the relation towards the union, used
        to locate the module in which the union entity lives.
    """
    path = owner_cls.__module__.split(".")[1:]
    key = (owner_cls.__module__, name)
    if key in _UNION_SCHEMA_CACHE:
        return _UNION_SCHEMA_CACHE[key]

    # The discriminator attribute takes whatever primitive type the literal
    # values of its members have.
    discriminator_field = members[0].model_fields[discriminator]

    schema = SliceEntitySchema(
        name=name,
        keys=members[0].keys,
        path=path,
        base_entities=[],
        sub_entities=[],
        description=f"Base entity for the members of the {name} discriminated union.",
        parent_entities=[],
        embedded_entities=[],
        attributes=[
            SliceEntityAttributeSchema(
                name=discriminator,
                description=discriminator_field.description,
                inmanta_type=to_inmanta_type(type(discriminator_field.default)),
            )
        ],
        discriminator=discriminator,
    )
    _UNION_SCHEMA_CACHE[key] = schema

    for member in members:
        member_schema = member.entity_schema()
        member_schema.discriminator_value = member.model_fields[discriminator].default
        if schema not in member_schema.base_entities:
            member_schema.base_entities = [*member_schema.base_entities, schema]
        for attr in member_schema.attributes:
            if attr.name == discriminator:
                attr.is_discriminator = True
        schema.sub_entities.append(member_schema)

    return schema


def relation_target_schema(
    element: object, owner_cls: type, *, fallback_name: str | None = None
) -> "SliceEntitySchema | None":
    """
    Resolve the entity schema a relation points to, for a single element type.
    This handles both a direct embedded slice class and a discriminated union
    of embedded slice classes.  Return None if the element is not a relation
    target.

    :param element: The element type of the relation (the class, the forward
        reference or the discriminated union annotation).
    :param owner_cls: The class on which the relation is defined.
    :param fallback_name: The name to use for a discriminated union when its
        name can not be derived from a forward reference.
    """
    union = discriminated_union(element, owner_cls, fallback_name=fallback_name)
    if union is not None:
        return union_schema(*union, owner_cls)

    resolved, _ = resolve_forward_reference(element, owner_cls)
    if inspect.isclass(resolved) and issubclass(resolved, EmbeddedSliceObjectABC):
        return resolved.entity_schema()

    return None


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
class SliceEntityParentSchema:
    """
    Schema of a parent of an embedded slice.  The parent is another
    entity referencing this slice for a specific relation.

    :attr name: The name of the relation on the parent pointing towards
        our embedded slice.
    :attr entity: The parent entity schema.
    """

    name: str
    entity: "SliceEntitySchema"


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
    :attr is_discriminator: When True, the attribute is the discriminator
        of a discriminated union.  On a member of the union, the attribute
        carries a fixed value taken from the entity's ``discriminator_value``.
    """

    name: str
    description: str | None
    inmanta_type: inmanta_type.Type
    is_discriminator: bool = False


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
    :attr sub_entities: The entity schemas which extend from this schema.
    :attr description: The description of the python class defining the
        entity, if there is any.
    :attr embedded_entities: A list of relations towards other slice entities.
    :attr attributes: A list of attributes defined on the entity.
    :attr discriminator: When this entity is the base of a discriminated union,
        the name of the attribute whose value identifies the concrete sub
        entity to use for a given instance.
    :attr discriminator_value: When this entity is part of a discriminated
        union, the fixed value its discriminator attribute takes for instances
        of this concrete entity.
    """

    name: str
    keys: Sequence[str]
    path: Sequence[str]
    base_entities: Sequence["SliceEntitySchema"]
    sub_entities: list["SliceEntitySchema"]
    description: str | None
    parent_entities: list[SliceEntityParentSchema]
    embedded_entities: Sequence[SliceEntityRelationSchema]
    attributes: Sequence[SliceEntityAttributeSchema]
    embedded_slice: bool = True
    discriminator: str | None = None
    discriminator_value: object | None = None

    def resolve(self, instance: dict) -> "SliceEntitySchema":
        """
        Resolve the concrete entity schema matching the given instance.  For a
        regular entity this is the entity itself.  For the base of a
        discriminated union, the sub entity whose discriminator value matches
        the one carried by the instance is returned.

        :param instance: The attributes dict of the instance to resolve.
        """
        if self.discriminator is None:
            return self

        value = instance.get(self.discriminator)
        for sub_entity in self.sub_entities:
            if sub_entity.discriminator_value == value:
                return sub_entity

        raise ValueError(
            f"No sub entity of {self.name} matches the discriminator "
            f"{self.discriminator}={value!r}"
        )

    def instance_identity(self, instance: dict) -> Sequence[tuple[str, object]]:
        """
        Calculate the identity of an instance of this type, based on the keys
        defined on this type.  When the entity is a member of a discriminated
        union, the discriminator is prepended to the identity so that two
        instances sharing the same keys but belonging to different concrete
        sub entities do not collide.
        """
        identity: list[tuple[str, object]] = []
        if self.discriminator_value is not None:
            discriminator = next(
                (
                    base.discriminator
                    for base in self.base_entities
                    if base.discriminator is not None
                ),
                None,
            )
            if discriminator is not None:
                identity.append(
                    (discriminator, str(instance[discriminator]))
                )
        identity.extend((k, str(instance[k])) for k in self.keys)
        return tuple(identity)

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

    def all_parents(self) -> typing.Iterator[SliceEntityParentSchema]:
        """
        Get all the entities to which this entity is attached via a relation.
        """
        return itertools.chain(
            self.parent_entities,
            *[sub_entity.all_parents() for sub_entity in self.sub_entities],
            [
                SliceEntityParentSchema(name="__root__", entity=sub_entity)
                for sub_entity in self.sub_entities
                if not sub_entity.embedded_slice
            ],
        )

    def has_many_parents(self) -> bool:
        """
        Returns True if this entity schema is referenced via relations by more
        than one parent slice.  If it is the case, the generator will need to
        generate a dedicated entity for each relation.

        When this schema is a member of a discriminated union, the parents of
        the union base are counted as additional parent contexts: the member
        inherits the parent relation of the union, so being part of a union
        adds one parent context to the count.
        """
        count = 0
        for _ in self.all_parents():
            count += 1
            if count > 1:
                return True

        if self.discriminator_value is not None:
            union_base = next(
                (
                    base
                    for base in self.base_entities
                    if base.discriminator is not None
                ),
                None,
            )
            if union_base is not None:
                count += len(union_base.parent_entities)

        return count > 1


def docstring(c: type) -> str | None:
    """
    Extract the docstring of a class definition (if there is any). Format
    it to remove the indentation.
    """
    if c.__doc__ is None:
        return None

    return textwrap.dedent(c.__doc__.strip("\n")).strip("\n")


class EmbeddedSliceObjectABC(pydantic.BaseModel):
    """
    Base class for all slice objects which are nested inside another slice.

    This class should be extended by any configuration object that is part of any slice.
    """

    keys: typing.ClassVar[Sequence[str]] = tuple()

    operation: SkipJsonSchema[str] = pydantic.Field(
        default="create",
        description=(
            "The operation attached to this part of the slice.  "
            "This dictates what to do with the model emitted by this slice (create/update/delete).  "
            "This value is not a user input, it is inserted into the slice source when the slice store is populated."
        ),
        exclude_if=slice_update,
    )
    path: SkipJsonSchema[str] = pydantic.Field(
        default=".",
        description=(
            "The path leading to this slice object, starting from the root of the slice definition.  "
            "This value should be a valid dict path expression."
        ),
        exclude_if=slice_update,
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
                and issubclass(base_class, EmbeddedSliceObjectABC)
            ],
            sub_entities=list(),
            description=docstring(cls),
            parent_entities=list(),
            embedded_entities=embedded_entities,
            attributes=attributes,
        )
        # Save entity into the cache
        setattr(cls, cached_attribute, entity_schema)

        # Make sure that each parent entity knows about all its sub entities
        for base_entity in entity_schema.base_entities:
            base_entity.sub_entities.append(entity_schema)

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
                target = relation_target_schema(
                    args[0], cls, fallback_name=attribute
                )
                if target is not None:
                    embedded_entities.append(
                        SliceEntityRelationSchema(
                            name=attribute,
                            description=info.description,
                            entity=target,
                            cardinality_min=0,
                            cardinality_max=None,
                        )
                    )
                    continue

            # Optional relation
            with contextlib.suppress(ValueError):
                optional = get_optional_type(python_type)
                target = relation_target_schema(
                    optional, cls, fallback_name=attribute
                )
                if target is not None:
                    embedded_entities.append(
                        SliceEntityRelationSchema(
                            name=attribute,
                            description=info.description,
                            entity=target,
                            cardinality_min=0,
                            cardinality_max=1,
                        )
                    )
                    continue

            # Required relation
            target = relation_target_schema(python_type, cls, fallback_name=attribute)
            if target is not None:
                embedded_entities.append(
                    SliceEntityRelationSchema(
                        name=attribute,
                        description=info.description,
                        entity=target,
                        cardinality_min=1,
                        cardinality_max=1,
                    )
                )
                continue

            # Couldn't parse the attribute, log a warning and continue
            raise ValueError(
                f"{cls}.{attribute} has an unsupported type annotation: {python_type}"
            )

        # Register this entity as a parent of all the entities towards which we
        # have a relation
        for relation in embedded_entities:
            relation.entity.parent_entities.append(
                SliceEntityParentSchema(
                    name=relation.name,
                    entity=entity_schema,
                )
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


class SliceObjectABC(EmbeddedSliceObjectABC):
    """
    Base class for the root of any slice definition.
    """

    version: SkipJsonSchema[int] = pydantic.Field(
        default=0,
        description="The version of this slice.  Every time the slice source is modified, it is incremented.",
        exclude_if=slice_update,
    )
    slice_store: SkipJsonSchema[str] = pydantic.Field(
        default="",
        description="The name of the store in which the instance of the slice is defined.",
        exclude_if=slice_update,
    )
    slice_name: SkipJsonSchema[str] = pydantic.Field(
        default="",
        description="The identifying name of the slice within its store.",
        exclude_if=slice_update,
    )

    @classmethod
    def entity_schema(cls) -> SliceEntitySchema:
        schema = super().entity_schema()
        schema.embedded_slice = False
        return schema
