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

import json
import pathlib
import typing

import pydantic
import yaml
from inmanta_plugins.config import resolve_path
from inmanta_plugins.config.const import InmantaPath, SystemPath

from inmanta.compiler import finalizer
from inmanta_plugins.git_ops import Slice

# Dict registering all the slice stores when they are being created
# This allows to find the store back, to access its slices.
SLICE_STORE_REGISTRY: dict[str, "SliceStore"] = {}


FileFormat = typing.Literal["json", "yaml"]


class SliceStore:
    """
    Store slices loaded from file into memory, keep track of their changes, and
    write them back to their original files at the end of the compile.
    """

    def __init__(
        self,
        name: str,
        folder: SystemPath | InmantaPath,
        *,
        format: FileFormat,
    ) -> None:
        """
        :param name: The name of the slice store, used to identify the
            store in any plugin that tries to access its slices.
        :param folder: The folder where the files defining the slices
            can be found.  Files in that folder should be valid yaml.
        """
        self.name = name
        self.path = pathlib.Path(resolve_path(folder))
        self.slices: dict[str, Slice] | None = None
        self.format = format
        self.register_store()

    def register_store(self) -> None:
        """
        Register this store into the slice store.  Raise an exception if
        another store with the same name already exists.
        """
        if self.name in SLICE_STORE_REGISTRY:
            raise RuntimeError(
                f"Store with name {self.name} can not be registered because another store with the same name already exists."
            )

        SLICE_STORE_REGISTRY[self.name] = self

    def read_slice(self, file: pathlib.Path) -> dict:
        """
        Read the content of a slice file, using the appropriate library,
        based on the expected file format.  Return the json-like object
        as a python dict.

        :param file: The full path to the file that should be read and
            parsed.
        """
        type_adapter = pydantic.TypeAdapter(dict)
        if self.format == "json":
            return type_adapter.validate_python(json.loads(file.read_text()))
        if self.format == "yaml":
            return type_adapter.validate_python(yaml.safe_load(file.read_text()))
        raise ValueError(f"Unsupported slice file format: {self.format}")

    def write_slice(self, file: pathlib.Path, attributes: dict) -> None:
        """
        Write the given attributes to the slice file.  The parent folder
        must exist.  The slice file can be absent, it will be created if
        it doesn't exist, overwritten if it does exist.

        :param file: The full path to the file that should be written.
        :param attributes: The raw slice attributes to write to the file.
        """
        if self.format == "json":
            return file.write_text(json.dumps(attributes))
        if self.format == "yaml":
            return file.write_text(yaml.safe_dump(attributes))
        raise ValueError(f"Unsupported slice file format: {self.format}")

    def load(self) -> list[Slice]:
        """
        Load all the slices from the files in the folder.
        """
        if self.slices is not None:
            return self.slices

        # Make sure the slice folder exists
        self.path.mkdir(parents=True, exist_ok=True)

        self.slices: dict[str, Slice] = {}
        for file in self.path.glob("*"):
            if not file.is_file():
                # Not a file, ignore it
                continue

            if file.name.startswith("."):
                # Hidden file, ignore it
                continue

            self.slices[file.name] = Slice(
                identifier=file.name,
                store_name=self.name,
                attributes=self.read_slice(file),
            )

        return list(self.slices.values())

    def save(self) -> None:
        """
        Save all the slices in the store back to file.
        """
        if self.slices is None:
            return

        for slice in self.slices.values():
            file = self.path / slice.identifier
            self.write_slice(file, slice.attributes)

    def clear(self) -> None:
        """
        Clear the cache of slices in memory.
        """
        self.slices = None

    def get_all_slices(self) -> list[Slice]:
        """
        Get all the slices, this method is similar to load, but more explicit.
        """
        return self.load()

    def get_one_slice(self, identifier: str) -> Slice:
        """
        Get one slice with the given identifier.  Raise a LookupError if it
        doesn't exist.

        :param identifier: The identifier of the slice.  Matching the name of
            the file defining the slice.
        """
        self.load()

        if identifier not in self.slices:
            raise LookupError(
                f"No slice with identifier {identifier} in store {self.name}. "
                f"Known slices are {self.slices.keys()}"
            )

        return self.slices[identifier]


def get_store(store_name: str) -> SliceStore:
    """
    Get the store with the given name, raise a LookupError if it
    doesn't exist.
    """
    if store_name not in SLICE_STORE_REGISTRY:
        raise LookupError(
            f"Cannot find any store named {store_name}.  Available stores are {SLICE_STORE_REGISTRY.keys()}"
        )

    return SLICE_STORE_REGISTRY[store_name]


@finalizer
def persist_store() -> None:
    """
    At the end of the compile, write all slices back to file and clear
    the in-memory cache.
    """
    for store in SLICE_STORE_REGISTRY.values():
        store.save()
        store.clear()
