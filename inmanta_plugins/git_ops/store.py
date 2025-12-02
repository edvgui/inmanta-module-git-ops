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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pydantic
import yaml
import yaml.error
from inmanta_plugins.config import resolve_path
from inmanta_plugins.config.const import InmantaPath, SystemPath

from inmanta.compiler import finalizer
from inmanta.execute.proxy import SequenceProxy
from inmanta.util import dict_path
from inmanta_plugins.git_ops import Slice, const, slice

# Dict registering all the slice stores when they are being created
# This allows to find the store back, to access its slices.
SLICE_STORE_REGISTRY: dict[str, "SliceStore[slice.SliceObjectABC]"] = {}


@dataclass(frozen=True, kw_only=True)
class SliceFile[S: slice.SliceObjectABC]:
    """
    Represent a file containing a slice definition.
    """

    path: pathlib.Path
    name: str
    version: int | None
    extension: str
    schema: type[S]

    def read(self) -> dict:
        """
        Read the content of a slice file, using the appropriate library,
        based on the file extension.  Return the json-like object
        as a python dict.
        """
        type_adapter = pydantic.TypeAdapter(self.schema)
        if self.extension == "json":
            attributes = type_adapter.validate_python(json.loads(self.path.read_text()))
        elif self.extension in ["yaml", "yml"]:
            attributes = type_adapter.validate_python(
                yaml.safe_load(self.path.read_text())
            )
        else:
            raise ValueError(f"Unsupported slice file extension: {self.extension}")

        if attributes == {}:
            # The slice has been deleted
            return {}
        else:
            # Load default values (and model only values)
            return (
                pydantic.TypeAdapter(self.schema)
                .validate_python(attributes)
                .model_dump(mode="json")
            )

    def write(self, attributes: dict) -> None:
        """
        Write the given attributes to the slice file.  The parent folder
        must exist.  The slice file can be absent, it will be created if
        it doesn't exist, overwritten if it does exist.

        :param attributes: The raw slice attributes to write to the file.
        """
        with slice.exclude_model_values():
            attributes = (
                (
                    pydantic.TypeAdapter(self.schema)
                    .validate_python(attributes)
                    .model_dump(mode="json")
                )
                if attributes != {}
                else {}
            )

        if self.extension == "json":
            try:
                return self.path.write_text(json.dumps(attributes, indent=2))
            except TypeError as e:
                raise ValueError(
                    f"Attributes can not be serialized: {attributes}"
                ) from e

        if self.extension in ["yaml", "yml"]:
            try:
                return self.path.write_text(yaml.safe_dump(attributes, sort_keys=False))
            except yaml.error.YAMLError as e:
                raise ValueError(
                    f"Attributes can not be serialized: {attributes}"
                ) from e

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
            schema=self.schema,
        )

    def emit_slice(
        self,
        store_name: str,
        default_version: int | None = None,
    ) -> Slice:
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
            name=self.name,
            store_name=store_name,
            version=version,
            attributes=attributes,
            deleted=attributes == {},
        )

    @classmethod
    def from_path[S: slice.SliceObjectABC](
        cls, file: pathlib.Path, schema: type[S]
    ) -> "SliceFile[S]":
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
            schema=schema,
        )


class SliceStore[S: slice.SliceObjectABC]:
    """
    Store slices loaded from file into memory, keep track of their changes, and
    write them back to their original files at the end of the compile.
    """

    def __init__(
        self,
        *,
        name: str,
        folder: SystemPath | InmantaPath,
        schema: type[S],
    ) -> None:
        """
        :param name: The name of the slice store, used to identify the
            store in any plugin that tries to access its slices.
        :param folder: The folder where the files defining the slices
            can be found.  Files in that folder should be valid yaml.
        """
        self.name = name
        self.schema = schema

        # The source folder and the slice files contained in it contain
        # user input.  The content of these files can be updated by plugins
        # while the slice is being activated.  Once the slice is active, it
        # is moved to the active slice directory and can not be modified
        self._folder = folder
        self._source_path: pathlib.Path | None = None
        self.source_slice_files: dict[str, SliceFile] | None = None
        self.source_slices: dict[str, Slice] | None = None

        self._active_path: pathlib.Path | None = None
        self.active_slice_files: dict[str, list[SliceFile]] | None = None
        self.active_slices: dict[tuple[str, int], Slice] | None = None

        # This dict contains all the resolved slices to be used in the
        # current compile
        self.current_slices: dict[str, Slice] | None = None
        self.previous_slices: dict[str, Slice] | None = None
        self.slices: dict[str, Slice] | None = None

        self.register_store()

    @property
    def source_path(self) -> pathlib.Path:
        """
        Lazy resolution of the source path, to allow constructing the slice object
        outside of an inmanta compile.
        """
        if self._source_path is None:
            self._source_path = pathlib.Path(resolve_path(self._folder))
        return self._source_path

    @property
    def active_path(self) -> pathlib.Path:
        """
        Lazy resolution of the active path, to allow constructing the slice object
        outside of an inmanta compile.
        """
        if self._active_path is None:
            self._active_path = pathlib.Path(
                resolve_path(f"inmanta:///git_ops/active/{self.name}/")
            )
        return self._active_path

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

            slice_file = SliceFile.from_path(file, self.schema)
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
            return Slice(
                name=name,
                store_name=self.name,
                version=0,
                attributes={},
                deleted=True,
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

            slice_file = SliceFile.from_path(file, self.schema)
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
                    name=name,
                    store_name=self.name,
                    version=latest.version + 1,
                    attributes={},
                    deleted=True,
                )

        return self.source_slices

    def load_current_slices(self) -> dict[str, Slice]:
        """
        Load all the previous slices (for slices which have an older version
        then the current latest one).
        """
        if self.current_slices is not None:
            return self.current_slices

        active_slices = self.load_active_slices()

        slices = set(active_slices.keys())
        if const.COMPILE_MODE in [const.COMPILE_UPDATE, const.COMPILE_SYNC]:
            # Activating compile, we need to look at the source of the
            # slices too
            slices |= self.load_source_slices().keys()

        self.current_slices: dict[str, Slice] = {}
        for s in slices:
            if const.COMPILE_MODE in [const.COMPILE_UPDATE, const.COMPILE_SYNC]:
                self.current_slices[s] = self.load_source_slices()[s]
            else:
                self.current_slices[s] = self.get_latest_slice(s)

        return self.current_slices

    def load_previous_slices(self) -> dict[str, Slice]:
        """
        Load all the previous slices (for slices which have an older version
        then the current latest one).
        """
        if self.previous_slices is not None:
            return self.previous_slices

        active_slices = self.load_active_slices()

        self.previous_slices: dict[str, Slice] = {}
        for s, current in self.load_current_slices().items():
            latest = self.get_latest_slice(s)

            previous = [
                s.attributes
                for s in sorted(
                    active_slices.get(s, []),
                    key=lambda s: s.version,
                    reverse=True,
                )
            ]
            if current == latest:
                previous = previous[1:]

            while len(previous) >= 2:
                p_current = previous[0]
                p_previous = previous[1]
                previous = [
                    merge_attributes(
                        p_current,
                        p_previous,
                        operation="delete",
                        path=dict_path.NullPath(),
                        schema=self.schema.entity_schema(),
                    ),
                    *previous[2:],
                ]

            if previous:
                self.previous_slices[s] = Slice(
                    name=s,
                    store_name=self.name,
                    version=current.version - 1,
                    attributes=previous[0],
                    deleted=False,
                )

        return self.previous_slices

    def load_slices(self) -> dict[str, Slice]:
        """
        Load all the slices defined in the project, for the current compile.
        If the compile is an activate compile, we load all the source slices
        and allocate them the right version, otherwise we only look at the
        already active slices.
        """
        if self.slices is not None:
            return self.slices

        previous_slices = self.load_previous_slices()

        self.slices: dict[str, Slice] = {}
        for s, current in self.load_current_slices().items():
            if current.deleted:
                # We need to get the attributes of the last undeleted
                # version, otherwise we don't know what we have to delete
                attributes = previous_slices[s].attributes
            else:
                # Normal merge
                new = s not in previous_slices
                attributes = merge_attributes(
                    current=current.attributes,
                    previous=None if new else previous_slices[s].attributes,
                    operation="create" if new else "update",
                    path=dict_path.NullPath(),
                    schema=self.schema.entity_schema(),
                )

            # Merge the current and previous slices together
            attributes["version"] = current.version
            attributes["slice_store"] = self.name
            attributes["slice_name"] = s
            self.slices[s] = Slice(
                name=s,
                store_name=self.name,
                version=current.version,
                attributes=attributes,
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
            changed_slices = [s.name for s in changed]
            raise RuntimeError(
                f"Sync blocked: some slices still contained some change: {changed_slices}"
            )

        for slice in self.source_slices.values():
            # The slice can be activated, create the file, then save the slice content
            # into it
            slice_file = SliceFile(
                path=self.active_path / f"{slice.name}@v{slice.version}.json",
                name=slice.name,
                version=slice.version,
                extension="json",
                schema=self.schema,
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
        self.current_slices = None
        self.previous_slices = None
        self.slices = None

    def get_all_slices(self) -> list[Slice]:
        """
        Get all the slices, this method is similar to load, but more explicit.
        """
        return list(self.load_slices().values())

    def get_one_slice(self, name: str) -> Slice:
        """
        Get one slice with the given name.  Raise a LookupError if it
        doesn't exist.

        :param name: The name of the slice.  Matching the name of
            the file defining the slice.
        """
        slices = self.load_slices()

        if name not in slices:
            raise LookupError(
                f"No slice with name {name} in store {self.name}. "
                f"Known slices are {slices.keys()}"
            )

        return slices[name]

    def json_value(self, raw_value: object) -> object:
        """
        Convert an immutable value (i.e. coming from the inmanta DSL) into
        a mutable, json-like python object.  Sequences are converted into
        lists, and Mappings into dicts.  Any other value is kept as is.

        :param raw_value: The raw value that should be converted.
        """
        match raw_value:
            case str():
                return raw_value
            case Sequence() | SequenceProxy():
                return [self.json_value(item) for item in raw_value]
            case Mapping():
                return {k: self.json_value(v) for k, v in raw_value.items()}
            case _:
                return raw_value

    def set_slice_attribute[T: object](
        self,
        name: str,
        path: dict_path.DictPath,
        value: T,
    ) -> T:
        """
        Update the attributes of the given slice in the source slice.
        If the compile is not an update compile, raise an exception.

        :param name: The name of the slice.
        :param path: The path withing the slice towards the attribute
            that should be set.
        :param value: The value that the attribute should be set to.
        """
        if const.COMPILE_MODE != const.COMPILE_UPDATE:
            raise RuntimeError(
                f"Slice attributes can only be updated during {const.COMPILE_UPDATE} compiles"
            )

        editable_value = self.json_value(value)

        path.set_element(self.load_source_slices()[name].attributes, editable_value)
        path.set_element(self.get_one_slice(name).attributes, editable_value)
        return editable_value

    def get_slice_attribute[T: object](
        self,
        name: str,
        path: dict_path.DictPath,
        *,
        default: T | None = None,
    ) -> T | None:
        """
        Get a slice attribute value located at the given path within the
        designated slice.

        :param name: The name of the slice.
        :param path: The path within the slice towards the attribute that
            should be fetched.
        :param default: The default value to return if the attribute doesn't
            exist in the slice.
        """
        try:
            return path.get_element(self.get_one_slice(name).attributes)
        except LookupError:
            return default

    def get_slice_previous_attribute[T: object](
        self,
        name: str,
        path: dict_path.DictPath,
        *,
        default: T | None = None,
    ) -> T | None:
        """
        Get the previous value of an attribute located at the given path in a slice.

        :param name: The name of the slice.
        :param path: The path within the slice towards the attribute that
            should be fetched.
        :param default: The default value to return if the attribute doesn't
            exist in the slice.
        """
        slices = self.load_previous_slices()
        if name not in slices:
            # No previous version for the given slice
            return default

        try:
            return path.get_element(slices[name].attributes)
        except LookupError:
            return default


def get_store(store_name: str) -> SliceStore[slice.SliceObjectABC]:
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


@finalizer
def clear_project_paths() -> None:
    """
    At the end of the compile, reset the paths that have been calculated based
    on the project dir.
    """
    for store in SLICE_STORE_REGISTRY.values():
        store._source_path = None
        store._active_path = None


def merge_attributes(
    current: dict,
    previous: dict | None,
    *,
    operation: typing.Literal["create", "update", "delete"],
    path: dict_path.DictPath,
    schema: slice.SliceEntitySchema,
) -> dict:
    """
    Construct a merge of the current and previous attributes, inserting
    all the attributes that were removed, marking them as purged. The
    merging capabilities are currently limited by the fact that no schema
    is provided.  We can only merge dicts, identifying any nested dict
    by the key that leads to it.  Any other type will be considered to be
    a primitive and the value of the current will be kept unmodified.
    """
    merged = {
        "operation": operation,
        "path": str(path),
    }

    # Go over all attributes, the merged value will always be the value
    # from the current
    for attribute in schema.all_attributes():
        if attribute.name in ["operation", "path"]:
            continue
        merged[attribute.name] = current.get(attribute.name)

    # Go over all relations
    for relation in schema.all_relations():
        cardinality = (relation.cardinality_min, relation.cardinality_max)
        if cardinality == (1, 1):
            # The relation is mandatory, we will always have the
            # current attributes
            merged[relation.name] = merge_attributes(
                current=typing.cast(dict, current[relation.name]),
                previous=(
                    typing.cast(dict, previous[relation.name])
                    if previous is not None
                    else None
                ),
                operation=operation,
                path=path + dict_path.InDict(relation.name),
                schema=relation.entity,
            )
            continue

        if cardinality == (0, 1):
            # Optional relation, see if the current value is still set, if it
            # is not, take the previous one and mark is as "delete"
            current_value = typing.cast(dict | None, current.get(relation.name))
            previous_value = (
                typing.cast(dict | None, previous.get(relation.name))
                if previous is not None
                else None
            )
            match (current_value, previous_value):
                case None, None:
                    merged[relation.name] = None
                case None, dict():
                    # Previous value should already have delete operation set
                    assert previous_value["operation"] == "delete"
                    merged[relation.name] = previous_value
                case dict(), _:
                    merged[relation.name] = merge_attributes(
                        current_value,
                        previous_value,
                        operation=(
                            operation
                            if operation == "delete"
                            else "create" if previous_value is None else "update"
                        ),
                        path=path + dict_path.InDict(relation.name),
                        schema=relation.entity,
                    )
                case _:
                    raise ValueError()
            continue

        # Relation, attribute should be a list, and should be merged
        current_values = {
            tuple(
                (k, str(current_value[k])) for k in relation.entity.keys
            ): current_value
            for current_value in typing.cast(list[dict], current[relation.name])
        }
        previous_values = {
            tuple(
                (k, str(previous_value[k])) for k in relation.entity.keys
            ): previous_value
            for previous_value in typing.cast(
                list[dict], previous[relation.name] if previous is not None else []
            )
        }
        merged_relation: list[dict] = []
        merged[relation.name] = merged_relation
        for key in current_values.keys() | previous_values.keys():
            current_value = current_values.get(key)
            previous_value = previous_values.get(key)
            match (current_value, previous_value):
                case None, dict():
                    # Previous value should already have delete operation set
                    assert previous_value["operation"] == "delete"
                    merged_relation.append(previous_value)
                case dict(), _:
                    merged_relation.append(
                        merge_attributes(
                            current_value,
                            previous_value,
                            operation=(
                                operation
                                if operation == "delete"
                                else "create" if previous_value is None else "update"
                            ),
                            path=path + dict_path.KeyedList(relation.name, key),
                            schema=relation.entity,
                        )
                    )
                case _:
                    raise ValueError()

    return merged
