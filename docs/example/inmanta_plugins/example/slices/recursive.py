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

from inmanta_plugins.git_ops import slice


class NamedSlice(slice.EmbeddedSliceObjectABC):
    """
    Base class for all slices identified with a name.
    """

    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str
    description: str | None = None


class EmbeddedSlice(NamedSlice):
    """
    Base class for all slices embedded into a parent slice.
    """

    unique_id: int | None = None

    # Test recursion
    recursive_slice: Sequence["EmbeddedSlice"] = []


class Slice(NamedSlice, slice.SliceObjectABC):
    """
    Main slice.
    """

    unique_id: int | None = None

    embedded_required: EmbeddedSlice
    embedded_optional: EmbeddedSlice | None = None
    embedded_sequence: Sequence[EmbeddedSlice] = []
