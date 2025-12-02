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
import pydantic
from pydantic.json_schema import SkipJsonSchema
from collections.abc import Sequence

from inmanta_plugins.git_ops import slice, store


class PathABC(slice.EmbeddedSliceObjectABC):
    """
    Base class for all files and directories represented in the slice.
    This class contains all of the shared attributes that both files and
    directories have.
    """
    
    keys: typing.ClassVar[Sequence[str]] = ["name"]

    name: str = pydantic.Field(
        description="The name of the filesystem element.  This name must be unique within the folder this element is part of."
    )
    permissions: str = pydantic.Field(
        default="770",
        description="The permissions to configure for this element.",
    )
    owner: str | None = pydantic.Field(
        default=None,
        description="The name or uid of the element owner."
    )
    group: str | None = pydantic.Field(
        default=None,
        description="The name or gid of the element group."
    )


class File(PathABC):
    """
    A text file in a folder, with its textual content.
    """
    
    content: str = pydantic.Field(
        default="",
        description="The textual content of the file."
    )
    previous_content: SkipJsonSchema[str | None] = pydantic.Field(
        default=None,
        description="The previous desired content of the file.",
        exclude_if=slice.slice_update,
    )


class Folder(PathABC):
    """
    A folder in the filesystem tree, containing files and other folders.
    """
    files: Sequence[File] = pydantic.Field(
        default_factory=list,
        description="A list of files to manage in the folder."
    )
    directories: Sequence["Folder"] = pydantic.Field(
        default_factory=list,
        description="A list of folder to manage within this folder."
    )


class RootFolder(slice.SliceObjectABC, Folder):
    """
    The root folder, and the root of the slice.
    """
    keys: typing.ClassVar[Sequence[str]] = ["root", "name"]

    root: str = pydantic.Field(
        description="The base path in the file system inside which this folder should be created."
    )


STORE = store.SliceStore(
    name="fs",
    folder="inmanta:///files/fs/",
    schema=RootFolder,
)
