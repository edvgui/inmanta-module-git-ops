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
from dataclasses import dataclass

from inmanta.plugins import plugin
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
) -> list[Slice]:
    """
    Find all the slices defined in the given folder, return them in a list
    of dicts.  The files are expected to be valid yaml files.
    """
    from inmanta_plugins.git_ops import store

    return store.get_store(store_name).get_all_slices()


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

    slice = store.get_store(store_name).get_one_slice(name)
    return dict_path.to_path(path).get_element(slice.attributes)


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

    slice = store.get_store(store_name).get_one_slice(name)
    dict_path.to_path(path).set_element(slice.attributes, value)
    return value
