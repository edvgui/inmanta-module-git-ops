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

import collections
import json
import pathlib
import re
import typing
from dataclasses import dataclass

import pydantic
import yaml
from inmanta_plugins.config import resolve_path
from inmanta_plugins.config.const import InmantaPath, SystemPath

from inmanta.compiler import finalizer
from inmanta.util import dict_path
from inmanta_plugins.git_ops import Slice, const

# Dict registering all the slice stores when they are being created
# This allows to find the store back, to access its slices.
SLICE_STORE_REGISTRY: dict[str, "SliceStore"] = {}


type FileFormat = typing.Literal["json", "yaml"]


@dataclass(frozen=True, kw_only=True)
class SliceFile:
    """
    Represent a file containing a slice definition.
    """

    path: pathlib.Path
    name: str
    version: int | None
    extension: str

    def read(self) -> dict:
        """
        Read the content of a slice file, using the appropriate library,
        based on the file extension.  Return the json-like object
        as a python dict.
        """
        type_adapter = pydantic.TypeAdapter(dict)
        if self.extension == "json":
            return type_adapter.validate_python(json.loads(self.path.read_text()))

        if self.extension in ["yaml", "yml"]:
            return type_adapter.validate_python(yaml.safe_load(self.path.read_text()))

        raise ValueError(f"Unsupported slice file extension: {self.extension}")

    def write(self, attributes: dict) -> None:
        """
        Write the given attributes to the slice file.  The parent folder
        must exist.  The slice file can be absent, it will be created if
        it doesn't exist, overwritten if it does exist.

        :param attributes: The raw slice attributes to write to the file.
        """
        if self.extension == "json":
            return self.path.write_text(json.dumps(attributes, indent=2))

        if self.extension in ["yaml", "yml"]:
            return self.path.write_text(yaml.safe_dump(attributes))

        raise ValueError(f"Unsupported slice file extension: {self.extension}")

    def with_version(self, version: int) -> "SliceFile":
        """
        Emit another slice file that is a copy of this one but with another
        version.
        """
        return SliceFile(
            path=self.path.with_name(f"{self.name}@v{version}.{self.extension}"),
            name=self.name,
            version=version,
            extension=self.extension,
        )

    def emit_slice(self, store_name: str, default_version: int | None = None) -> Slice:
        """
        Construct the slice containing in this file.  If the slice file is not
        versioned (source slice) then assign the given default version. If no
        default version is provided, raise an exception.

        :param store_name: The name of the store this slice belongs into.
        :param default_version: If the slice is a source slice, the version that
            should be assigned to it.
        """
        version = self.version
        if version is None:
            version = default_version

        if version is None:
            raise ValueError(
                "Active slices must have a version specified in the file name.  "
                f"File {self.path} is missing such version."
            )

        # Read the slice content
        attributes = self.read()

        return Slice(
            identifier=self.name,
            store_name=store_name,
            version=version,
            attributes=attributes,
            deleted=not attributes,
        )

    @classmethod
    def from_path(cls, file: pathlib.Path) -> "SliceFile":
        """
        Parse the name of a file containing a slice.  The name of the file
        should contain the name of the slice, optionally the version, and
        always a valid file extension.

        The result is returned as a dict

        :param file: The path to a file whose name we want to parse.
        """
        matched = re.fullmatch(
            r"(?P<name>[^@]+)(\@v(?P<version>\d+))?\.(?P<extension>[a-z]+)",
            str(file.name),
        )
        if not matched:
            raise ValueError(f"Can not parse slice filename at {file}")

        # Version is optional, it will either match or be None
        version: str | None = matched.group("version")

        return SliceFile(
            path=file,
            name=matched.group("name"),
            version=int(version) if version is not None else None,
            extension=matched.group("extension"),
        )


class SliceStore:
    """
    Store slices loaded from file into memory, keep track of their changes, and
    write them back to their original files at the end of the compile.
    """

    def __init__(
        self,
        name: str,
        folder: SystemPath | InmantaPath,
    ) -> None:
        """
        :param name: The name of the slice store, used to identify the
            store in any plugin that tries to access its slices.
        :param folder: The folder where the files defining the slices
            can be found.  Files in that folder should be valid yaml.
        """
        self.name = name

        # The source folder and the slice files contained in it contain
        # user input.  The content of these files can be updated by plugins
        # while the slice is being activated.  Once the slice is active, it
        # is moved to the active slice directory and can not be modified
        self.source_path = pathlib.Path(resolve_path(folder))
        self.source_slice_files: dict[str, SliceFile] | None = None
        self.source_slices: dict[str, Slice] | None = None

        self.active_path = pathlib.Path(
            resolve_path(f"inmanta:///git_ops/active/{self.name}/")
        )
        self.active_slice_files: dict[str, list[SliceFile]] | None = None
        self.active_slices: dict[tuple[str, int], Slice] | None = None

        # This dict contains all the resolved slices to be used in the
        # current compile
        self.slices: dict[str, Slice] | None = None

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

    def load_active_slice_files(self) -> dict[str, list[SliceFile]]:
        """
        Load all the files defining slices in the active folder.
        """
        if self.active_slice_files is not None:
            return self.active_slice_files

        # Make sure the slice folder exists
        self.active_path.mkdir(parents=True, exist_ok=True)

        self.active_slice_files: dict[str, list[SliceFile]] = collections.defaultdict(
            list
        )
        for file in self.active_path.glob("*"):
            if not file.is_file():
                # Not a file, ignore it
                continue

            if file.name.startswith("."):
                # Hidden file, ignore it
                continue

            slice_file = SliceFile.from_path(file)
            self.active_slice_files[slice_file.name].append(slice_file)

        return self.active_slice_files

    def load_active_slices(self) -> dict[str, list[Slice]]:
        """
        Load all the active slices.
        """
        if self.active_slices is not None:
            return self.active_slices

        self.active_slices = {
            slice: [slice_file.emit_slice(self.name) for slice_file in slice_files]
            for slice, slice_files in self.load_active_slice_files().items()
        }
        return self.active_slices

    def get_latest_slice(self, name: str) -> Slice:
        """
        Get the latest version of the given active slice.
        """
        active_slices = self.load_active_slices()
        if name not in active_slices:
            raise LookupError(
                f"Can not find any slice named {name} in slice store {self.name}"
            )

        slices = sorted(
            active_slices[name],
            key=lambda s: s.version,
            reverse=True,
        )
        return slices[0]

    def load_source_slice_files(self) -> dict[str, SliceFile]:
        """
        Load all the files defining slices in the source folder.
        """
        if self.source_slice_files is not None:
            return self.source_slice_files

        # Make sure the slice folder exists
        self.source_path.mkdir(parents=True, exist_ok=True)

        self.source_slice_files: dict[str, SliceFile] = {}
        for file in self.source_path.glob("*"):
            if not file.is_file():
                # Not a file, ignore it
                continue

            if file.name.startswith("."):
                # Hidden file, ignore it
                continue

            slice_file = SliceFile.from_path(file)
            self.source_slice_files[slice_file.name] = slice_file

        return self.source_slice_files

    def load_source_slices(self) -> dict[str, Slice]:
        """
        Load all the source slices, compare each slice with the latest active slice
        of to figure out the version.
        """
        if self.source_slices is not None:
            return self.source_slices

        active_slices = self.load_active_slices()
        source_slice_files = self.load_source_slice_files()

        self.source_slices: dict[str, Slice] = {}
        for name, slice_file in source_slice_files.items():
            if name not in active_slices:
                # First version of the slice
                self.source_slices[name] = slice_file.emit_slice(
                    store_name=self.name,
                    default_version=1,
                )
                continue

            # Get the latest active slice with this name
            latest = self.get_latest_slice(name)

            # Load the source slice and compare it to the latest slice
            attributes = slice_file.read()
            if attributes == latest.attributes:
                # Same attributes, same version, same slice
                self.source_slices[name] = latest
            else:
                # Different attributes, next version, new slice
                self.source_slices[name] = slice_file.emit_slice(
                    store_name=self.name,
                    default_version=latest.version + 1,
                )

        # Deleted slices still need to be added to the source slices
        deleted_slices = active_slices.keys() - self.source_slices.keys()
        for name in deleted_slices:
            latest = self.get_latest_slice(name)
            if latest.deleted:
                # Latest is already deleted, same slice
                self.source_slices[name] = latest
            else:
                # Latest is not deleted, emit a new deleted slice
                self.source_slices[name] = Slice(
                    identifier=name,
                    store_name=self.name,
                    version=latest.version + 1,
                    attributes={},
                    deleted=True,
                )

        return self.source_slices

    def load_slices(self) -> dict[str, Slice]:
        """
        Load all the slices defined in the project, for the current compile.
        If the compile is an activate compile, we load all the source slices
        and allocate them the right version, otherwise we only look at the
        already active slices.
        """
        if self.slices is not None:
            return self.slices

        active_slices = self.load_active_slices()

        slices = set(active_slices.keys())
        if const.COMPILE_MODE in [const.COMPILE_UPDATE, const.COMPILE_SYNC]:
            # Activating compile, we need to look at the source of the
            # slices too
            slices |= self.load_source_slices().keys()

        self.slices: dict[str, Slice] = {}
        for slice in slices:
            if const.COMPILE_MODE in [const.COMPILE_UPDATE, const.COMPILE_SYNC]:
                current = self.load_source_slices()[slice]
            else:
                current = self.get_latest_slice(slice)

            previous = active_slices.get(slice, [])

            # Merge the current and previous slices together
            self.slices[slice] = Slice(
                identifier=slice,
                store_name=self.name,
                version=current.version,
                attributes=merge_attributes(
                    current=current.attributes,
                    previous=[p.attributes for p in previous],
                    path=dict_path.NullPath(),
                ),
                deleted=current.deleted,
            )

        return self.slices

    def sync(self) -> None:
        """
        Activate all the source slices.  For each source slice whose version is
        not present in the active store, add them there and save them to file.
        """
        if const.COMPILE_MODE != const.COMPILE_SYNC:
            raise RuntimeError(
                "Source slices can only be activated during an activating compile"
            )

        if self.source_slices is None:
            return

        # Validate that none of the source slices has changed
        changed: list[Slice] = []
        for name, slice_file in self.load_source_slice_files().items():
            slice = self.source_slices[name]
            if slice_file.read() != slice.attributes:
                # Changed detected for a slice, register the change and save it to file so it is not lost
                changed.append(slice)
                slice_file.write(slice.attributes)

        if changed:
            changed_slices = [s.identifier for s in changed]
            raise RuntimeError(
                f"Sync blocked: some slices still contained some change: {changed_slices}"
            )

        for slice in self.source_slices.values():
            # The slice can be activated, create the file, then save the slice content
            # into it
            slice_file = SliceFile(
                path=self.active_path / f"{slice.identifier}@v{slice.version}.json",
                name=slice.identifier,
                version=slice.version,
                extension="json",
            )
            slice_file.write(slice.attributes)

    def update(self) -> None:
        """
        Save all the source slices in the store back to file.
        """
        if self.source_slices is None:
            return

        for slice_file in self.load_source_slice_files().values():
            slice = self.source_slices[slice_file.name]
            slice_file.write(slice.attributes)

    def clear(self) -> None:
        """
        Clear the cache of slices in memory.
        """
        self.source_slice_files = None
        self.source_slices = None
        self.active_slice_files = None
        self.active_slices = None
        self.slices = None

    def get_all_slices(self) -> list[Slice]:
        """
        Get all the slices, this method is similar to load, but more explicit.
        """
        return list(self.load_slices().values())

    def get_one_slice(self, identifier: str) -> Slice:
        """
        Get one slice with the given identifier.  Raise a LookupError if it
        doesn't exist.

        :param identifier: The identifier of the slice.  Matching the name of
            the file defining the slice.
        """
        slices = self.load_slices()

        if identifier not in slices:
            raise LookupError(
                f"No slice with identifier {identifier} in store {self.name}. "
                f"Known slices are {slices.keys()}"
            )

        return slices[identifier]


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
        if const.COMPILE_MODE == const.COMPILE_UPDATE:
            store.update()
        elif const.COMPILE_MODE == const.COMPILE_SYNC:
            store.sync()
        else:
            pass
        store.clear()


def merge_attributes(
    current: dict,
    previous: list[dict],
    *,
    path: dict_path.DictPath,
) -> dict:
    """
    Construct a merge of the current and previous attributes, inserting
    all the attributes that were removed, marking them as purged. The
    merging capabilities are currently limited by the fact that no schema
    is provided.  We can only merge dicts, identifying any nested dict
    by the key that leads to it.  Any other type will be considered to be
    a primitive and the value of the current will be kept unmodified.
    """
    merged = dict()

    keys = set(current.keys())
    for p in previous:
        keys |= p.keys()

    for k in keys:
        c = current.get(k)
        p = [v for p in previous if (v := p.get(k)) is not None]

        if isinstance(c, (str, int, float, bool)):
            # Primitive, there is no merging, we just use the current
            merged[k] = c
            continue

        if isinstance(c, list):
            # List, we can also not merge it, whether it is a list of
            # primitives or not because we currently don't have any
            # schema to identify nested slices
            merged[k] = c
            continue

        if len(p) == 0:
            # No previous values, whatever we have for current is all we
            # have
            merged[k] = c
            continue

        if c is None:
            # Current state is either a None primitive, or a removed
            # value that a previous state still has.
            # If the previous states are dicts, we need to merge them
            # and insert them into the current, marked as "purged"
            try:
                previous_dicts = pydantic.TypeAdapter(list[dict]).validate_python(p)
                if len(previous_dicts) == 1:
                    v = dict(previous_dicts[0])
                    v["_path"] = str(path + dict_path.InDict(k))
                else:
                    v = merge_attributes(
                        current=dict(previous_dicts[0]),
                        previous=previous_dicts[1:],
                        path=path + dict_path.InDict(k),
                    )

                v["_purged"] = True
                merged[k] = v
                continue
            except pydantic.ValidationError:
                # The previous doesn't contain dicts, we consider our
                # None to be a primitive
                merged[k] = c
                continue

        # From now on, we should only have dicts, we recurse the merging
        merged[k] = merge_attributes(
            current=pydantic.TypeAdapter(dict).validate_python(c),
            previous=pydantic.TypeAdapter(list[dict]).validate_python(p),
            path=path + dict_path.InDict(k),
        )

    merged["_path"] = str(path)
    return merged
