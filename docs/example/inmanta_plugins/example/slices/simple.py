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
import typing

import pydantic
from inmanta_plugins.git_ops import slice


class Slice(slice.SliceObjectABC):
    """
    Main slice.
    """
    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str = pydantic.Field(description="The name of the slice.")
    description: str | None = pydantic.Field(
        default=None,
        description="A helpful description of the slice's function.",
    )
    unique_id: int | None = pydantic.Field(
        default=None,
        description="A unique identifier automatically assigned to this slice.",
    )
    some_number: float = pydantic.Field(
        default=0.0,
        description="An example of number field.",
    )
    some_flag: bool = pydantic.Field(
        default=False,
        description="An example of boolean field.",
    )
    some_list: Sequence[str] = pydantic.Field(
        default_factory=list,
        description="An example of list field.",
    )
    some_dict: dict = pydantic.Field(
        default_factory=dict,
        description="An example of dict field.",
    )
