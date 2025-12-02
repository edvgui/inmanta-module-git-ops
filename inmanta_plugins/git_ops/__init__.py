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
import typing
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from inmanta.plugins import Plugin, plugin
from inmanta.util import dict_path

type CompileMode = typing.Literal["update", "sync", "export"]


@dataclass(frozen=True, kw_only=True)
class Slice:
    name: str
    store_name: str
    version: int
    attributes: dict
    deleted: bool = False


@plugin
def unroll_slices(
    store_name: str,
) -> list[dict]:
    """
    Find all the slices defined in the given folder, return them in a list
    of dicts.  The files are expected to be valid yaml files.
    """
    from inmanta_plugins.git_ops import store

    all_slices = store.get_store(store_name).get_all_slices()
    return [asdict(s) for s in all_slices]


@plugin
def attributes(
    slice_object_type: str,
    slice_object_attr: dict,
    skip_attributes: Sequence[str] = [],
    **overrides: object,
) -> dict[str, object]:
    """
    Extract all the primitive attributes from the given slice object
    attributes dict (living out any relational attribute).  To do this,
    the slice object type is required, in python or dsl format.

    Any additional attribute can be provided and will be passed transparently.
    This is handy for usage with processors which also need to update the
    content of the attributes.

    :param slice_object_type: The type name of the object that will receive
        all the attributes values.
    :param slice_object_attr: The attributes dict, as returned by unroll_slices.
    :param skip_attributes: Names of attributes which should not be part of the
        dict.  Can be handy for processed attributes which need to have access
        to the entity object itself.
    :param **overrides: Values that should be returned instead of the attribute
        value currently in the dict.
    """
    # Convert dsl type to python type
    if "::" in slice_object_type:
        slice_object_type = "inmanta_plugins." + slice_object_type.replace("::", ".")

    # Find the python class
    class_name = slice_object_type.split(".")[-1]
    slice_object_module = importlib.import_module(
        slice_object_type.removesuffix(f".{class_name}")
    )
    slice_object_cls = getattr(slice_object_module, class_name)

    # Make sure the class is a valid slice
    from inmanta_plugins.git_ops import slice

    if not issubclass(slice_object_cls, slice.EmbeddedSliceObjectABC):
        raise ValueError(
            f"Class {slice_object_type} (from {slice_object_type}) is not a valid Slice definition."
        )

    # Construct the dict containing only the primitive attributes
    return {
        attr.name: overrides.get(attr.name, slice_object_attr[attr.name])
        for attr in slice_object_cls.entity_schema().all_attributes()
        if attr.name not in skip_attributes
    }


@plugin
def get_slice_previous_attribute(
    store_name: str,
    name: str,
    path: str,
    *,
    default: object | None = None,
) -> object:
    """
    Get the previous value of an attribute located at the given path in a slice.
    The path should be a valid dict path expression.

    :param store_name: The name of the store in which the slice is defined.
    :param name: The name of the slice within the store.
    :param path: The path within the slice's attributes towards the value that
        should be fetched.
    :param default: Default value to return in case the attribute doesn't exist
        in the previous version of the slice.
    """
    from inmanta_plugins.git_ops import store

    return store.get_store(store_name).get_slice_previous_attribute(
        name,
        dict_path.to_path(path),
        default=default,
    )


@plugin
def get_slice_attribute(
    store_name: str,
    name: str,
    path: str,
) -> object:
    """
    Get an attribute of a slice at a given path.  The path should be a valid
    dict path expression.

    :param store_name: The name of the store in which the slice is defined.
    :param name: The name of the slice within the store.
    :param path: The path within the slice's attributes towards the value that
        should be fetched.
    """
    from inmanta_plugins.git_ops import store

    return store.get_store(store_name).get_slice_attribute(
        name, dict_path.to_path(path)
    )


@plugin
def update_slice_attribute(
    store_name: str,
    name: str,
    path: str,
    value: object,
) -> object:
    """
    Update the content of a slice at a given path.  The path should be a valid
    dict path expression.

    :param store_name: The name of the store in which the slice is defined.
    :param name: The name of the slice within the store.
    :param path: The path within the slice's attributes towards the value that
        should be updated.
    :param value: The value that should be inserted into the slice attributes.
    """
    from inmanta_plugins.git_ops import store

    return store.get_store(store_name).set_slice_attribute(
        name, dict_path.to_path(path), value
    )


class AttributeProcessorFunction[**P, R](typing.Protocol):
    """
    Define the interface that processor functions must implement.
    """

    def __call__(
        self,
        store_name: str,
        name: str,
        path: str,
        previous_value: R | None,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        pass


def attribute_processor[F: AttributeProcessorFunction](func: F) -> F:
    """
    Register a function as an attribute processor.  Attribute processors are
    called during update compile to process the value of a slice attribute and
    potentially change it.  The value returned by the processor is saved back
    into the slice at the end of the compile.  For non-update compiles, the
    function calls are by-passed and the value of the slice is returned as is.

    .. code-block:: python

        @attribute_processor
        def upper(
            store_name: str,
            name: str,
            path: str,
            previous_value: str | None,
        ) -> str | None:
            if previous_value is not None:
                return previous_value.upper()
            else:
                return None

    :param func: The processor function to register and wrap.
    """
    from inmanta_plugins.git_ops import const

    # Make sure that the inmanta compiler sees this wrapped function the same way
    # as the plugin it wraps, with its annotations and defaults
    @functools.wraps(
        wrapped=func,
        assigned=(*functools.WRAPPER_ASSIGNMENTS, "__defaults__", "__kwdefaults__"),
    )
    def wrapped(
        self: Plugin,
        store_name: str,
        name: str,
        path: str,
        previous_value: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        """
        Wrapper function, getting the value from the slice and, if this is an
        update compile, also call the processor function and return its result.

        :param store_name: The name of the slice store in which the slice is.
        :param name: The name of the slice.
        :param path: The path within the slice's attributes towards the value that
            should be updated.
        :param previous_value: The value that is currently in the slice for the
            given attribute.
        """
        # Get the value that is currently set in the slice
        previous_value = get_slice_attribute(store_name, name, path)

        if const.COMPILE_MODE != const.COMPILE_UPDATE:
            # The slice can not be updated, we keep whatever value we have
            return previous_value

        # Call the processor and set the new value in the slice
        return update_slice_attribute(
            store_name,
            name,
            path,
            func(
                store_name,
                name,
                path,
                previous_value,
                *args,
                **kwargs,
            ),
        )

    # Register the original plugin
    plugin(func)

    # Overwrite the call method of the plugin with our wrapper
    func.__plugin__.call = wrapped  # type: ignore

    return wrapped
