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
import itertools
import json
import logging
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
from inmanta_plugins.git_ops import Slice, config, const, get_parent_path, slice

# Dict registering all the slice stores when they are being created
# This allows to find the store back, to access its slices.
SLICE_STORE_REGISTRY: dict[str, "SliceStore[slice.SliceObjectABC]"] = {}


LOGGER = logging.getLogger(__name__)


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

    def read_raw(self) -> dict:
        """
        Read the content of a slice file, without applying any schema
        validation.  This is useful for migrations, where the file on
        disk may predate the current schema.
        """
        if self.extension == "json":
            attributes = json.loads(self.path.read_text())
        elif self.extension in ["yaml", "yml"]:
            attributes = yaml.safe_load(self.path.read_text())
        else:
            raise ValueError(f"Unsupported slice file extension: {self.extension}")

        if attributes is None:
            return {}
        if not isinstance(attributes, dict):
            raise ValueError(f"Slice file {self.path} does not contain a json mapping")
        return attributes

    def read(self) -> dict:
        """
        Read the content of a slice file, using the appropriate library,
        based on the file extension.  Return the json-like object
        as a python dict.
        """
        attributes = self.read_raw()

        if attributes == {}:
            # The slice has been deleted
            return {}

        # Load default values (and model only values)
        return (
            pydantic.TypeAdapter(self.schema)
            .validate_python(attributes)
            .model_dump(mode="json")
        )

    def write_raw(self, attributes: dict) -> None:
        """
        Write the given raw attributes to the slice file, preserving the
        file's extension, without applying any schema validation.  This
        is useful for migrations, where the attributes may not yet
        conform to the current schema.
        """
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

        self.write_raw(attributes)

    def delete(self) -> None:
        """
        Delete the slice file from the filesystem.  If the file doesn't exist, do nothing.
        """
        if self.path.exists():
            self.path.unlink()

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


class SliceStoreMigrations(pydantic.BaseModel):
    """
    This model is used to keep track of the migrations applied to a slice store.
    It is stored in a hidden file in the active folder of the store, and updated
    after every successful migration.
    """

    applied: list[str] = []


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

        # This is the path to the file keeping track of the applied migrations for this store
        self._migration_state_path: pathlib.Path | None = None

        # The migrations registered for this store.
        self.migrations: dict[str, typing.Callable[[dict], dict]] = {}

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

    @property
    def migration_state_path(self) -> pathlib.Path:
        """
        Lazy resolution of the migration state path, to allow constructing the slice object
        outside of an inmanta compile.
        """
        if self._migration_state_path is None:
            self._migration_state_path = self.active_path / ".migrations.json"
        return self._migration_state_path

    def migration[F: typing.Callable[[dict], dict]](
        self, name: str
    ) -> typing.Callable[[F], F]:
        """
        Register a function as a migration for this slice store.

        The function receives the raw attributes of a slice (as a python dict)
        and must return the migrated attributes.  Empty dicts (``{}``) indicate
        deleted slices and are not passed to the migration function.

        :param name: A unique name identifying this migration within the store.
            The name is used to remember that the migration has been applied
            and must not be reused or renamed once published.  Migrations are
            applied in alphabetical order of their names, so a common convention
            is to prefix the name with the date.
            i.e. ``"2024-06-01-add-foo-field"``.
        """

        def decorator(func: F) -> F:
            if name in self.migrations:
                raise ValueError(
                    f"Migration {name!r} is already registered for store {self.name!r}"
                )

            self.migrations[name] = func
            return func

        return decorator

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

        if const.COMPILE_MODE == const.COMPILE_EMPTY:
            # Empty compile, we shouldn't load any slice
            return self.active_slice_files

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

        # Before loading the active slices, we need to run all the pending migrations,
        # to make sure the active slices are up to date with the latest schema.  This
        # is important because the source slices will be compared to the active slices
        # to determine their version, and if the active slices are not up to date, we
        # might end up with incorrect versions for the source slices, which can cause
        # problems during the compile.
        self.migrate()

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

        if const.COMPILE_MODE == const.COMPILE_EMPTY:
            # Empty compile, we shouldn't load any slice
            return self.source_slice_files

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

        # Before loading the source slices, we need to run all the pending migrations, to make
        # sure the active slices are up to date with the latest schema.  This is important because
        # the source slices will be compared to the active slices to determine their version, and
        # if the active slices are not up to date, we might end up with incorrect versions for the
        # source slices, which can cause problems during the compile.
        self.migrate()

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
                        operation=const.SLICE_DELETE,
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

        if const.COMPILE_MODE == const.COMPILE_PRUNE:
            # In prune compile, we want to ignore all the slices, we just want to
            # delete the unused ones
            self.slices = {}
            return self.slices

        previous_slices = self.load_previous_slices()

        self.slices: dict[str, Slice] = {}
        for s, current in self.load_current_slices().items():
            if current.deleted:
                # We need to get the attributes of the last undeleted
                # version, otherwise we don't know what we have to delete
                attributes = merge_attributes(
                    current=previous_slices[s].attributes,
                    previous=previous_slices[s].attributes,
                    operation=const.SLICE_DELETE,
                    path=dict_path.NullPath(),
                    schema=self.schema.entity_schema(),
                )
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

    def applied_migrations(self) -> list[str]:
        """
        Get the list of applied migrations for this store, in the order they were applied.
        """
        if not self.migration_state_path.exists():
            return []

        try:
            LOGGER.debug(
                "Loading migration state for store %s from %s",
                self.name,
                self.migration_state_path,
            )
            raw = json.loads(self.migration_state_path.read_text())
            return (
                pydantic.TypeAdapter(SliceStoreMigrations).validate_python(raw).applied
            )
        except (json.JSONDecodeError, pydantic.ValidationError) as e:
            LOGGER.error(
                "Invalid migration state file at %s: %s", self.migration_state_path, e
            )
            raise ValueError(
                f"Invalid migration state file at {self.migration_state_path}"
            ) from e

    def pending_migrations(self) -> list[str]:
        """
        Get the list of pending migrations for this store, in the order they should be applied.
        A migration is pending if it is registered in the store but not yet applied to the active slices.
        """
        applied = set(self.applied_migrations())
        pending = sorted(name for name in self.migrations.keys() if name not in applied)
        LOGGER.debug(f"Pending migrations for store {self.name}: {pending}")
        return pending

    def apply_migration(self, name: str) -> None:
        """
        Apply the given migration to all the active and source slices.
        The migration is applied by reading the raw attributes of each active slice, passing them through the
        migration function, and writing back the migrated attributes to the source slice file.  Once all the
        slices have been migrated, the migration is marked as applied in the migration state file.

        :param name: The name of the migration to apply.
        """
        if name not in self.migrations:
            raise ValueError(
                "No migration with name %s registered for store %s", name, self.name
            )

        LOGGER.debug(f"Applying migration {name} for store {self.name}")
        migration_func = self.migrations[name]

        # First try to apply the migration to all the slices, to make sure it works on all of them, before writing
        # any change to file.  This way we avoid leaving the store in a broken state if the migration fails halfway through.
        slice_files: list[SliceFile] = itertools.chain(
            self.load_source_slice_files().values(),
            *self.load_active_slice_files().values(),
        )
        updated_slices: list[tuple[SliceFile, dict]] = []
        for slice_file in slice_files:
            raw_attributes = slice_file.read_raw()
            if raw_attributes == {}:
                # Deleted slice, skip it
                continue

            LOGGER.log(
                0,
                "Applying migration %s to slice %s with attributes %s",
                name,
                slice_file.path,
                raw_attributes,
            )
            try:
                migrated_attributes = migration_func(raw_attributes)
            except Exception as e:
                raise RuntimeError(
                    f"Error occurred while applying migration {name} to slice {slice_file.path}: {e}"
                ) from e

            updated_slices.append((slice_file, migrated_attributes))

        # Then save the migrated attributes for all the slices, now that we know the migration works on all of them
        for slice_file, migrated_attributes in updated_slices:
            try:
                slice_file.write_raw(migrated_attributes)
            except Exception as e:
                raise RuntimeError(
                    f"Error occurred while writing migrated attributes for slice {slice_file.path} during migration {name}: {e}"
                ) from e

        # Mark the migration as applied
        applied = self.applied_migrations()
        applied.append(name)
        self.migration_state_path.write_text(
            json.dumps(SliceStoreMigrations(applied=applied).model_dump(), indent=2)
        )

    def migrate(self) -> None:
        """
        Run all the pending migrations for this store.
        A migration is pending if it is registered in the store but not yet applied to the active and source slices.
        """
        pending = self.pending_migrations()

        if pending and const.COMPILE_MODE != const.COMPILE_UPDATE:
            raise RuntimeError(
                "Migrations can only be applied during an update compile, but the current "
                f"compile mode is {const.COMPILE_MODE} and some pending migrations are detected "
                f"for store {self.name}: {pending}"
            )

        for migration_name in self.pending_migrations():
            self.apply_migration(migration_name)

    def sync(self) -> None:
        """
        Activate all the source slices.  For each source slice whose version is
        not present in the active store, add them there and save them to file.
        """
        if const.COMPILE_MODE != const.COMPILE_SYNC:
            raise RuntimeError(
                "Source slices can only be activated during an activating compile, "
                f"but the current compile mode is {const.COMPILE_MODE}"
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

    def prune(self) -> None:
        """
        Remove all the slices from the store that are not in use.
        These are the slices which have a more recent version, or which are deleted.
        """
        if const.COMPILE_MODE != const.COMPILE_PRUNE:
            raise RuntimeError("Slices can only be pruned during a prune compile")

        active_slice_files = self.load_active_slice_files()
        for slice_files in active_slice_files.values():
            latest_slice_file = max(slice_files, key=lambda s: s.version or 0)
            for slice_file in slice_files:
                if slice_file != latest_slice_file:
                    # This slice file is not the latest version, it should be pruned
                    slice_file.delete()

            if latest_slice_file.read_raw() == {}:
                # The latest slice file is deleted, it should be pruned too
                latest_slice_file.delete()

    def update(self) -> None:
        """
        Save all the source slices in the store back to file.  If a schema
        path is provided for this store config, also update the schema file.
        """
        if self.source_slices is None:
            return

        for slice_file in self.load_source_slice_files().values():
            slice = self.source_slices[slice_file.name]
            slice_file.write(slice.attributes)

        schema_path = config.SliceStoreConfig.get_for_store(self.name).schema_path
        if schema_path is not None:
            schema_path = pathlib.Path(resolve_path(schema_path))
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text(
                json.dumps(self.schema.model_json_schema(), indent=2)
            )

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
        return sorted(self.load_slices().values(), key=lambda s: s.name)

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

        # Get the parent slice, make sure it is not being deleted, otherwise
        # we can not write to it
        source = self.load_source_slices()[name].attributes

        try:
            # If the embedded slice is the root slice, we just get the empty
            # slice
            parent_value = get_parent_path(path).get_element(source)
        except LookupError:
            # If the embedded slice has been removed, we get a lookup
            # error
            parent_value = {}

        if parent_value.get("operation", const.SLICE_DELETE) == const.SLICE_DELETE:
            raise RuntimeError(
                f"Can not set attribute on deleted slice: {repr(str(parent_value))} in "
                f"Slice(name={repr(name)}) is deleted from source slice and can not "
                "be modified."
            )

        # Edit the source slice, so it gets saved back to file
        path.set_element(source, editable_value)

        # Edit the merged slice, so the change is visible in the model
        path.set_element(self.get_one_slice(name).attributes, editable_value)

        # Return the editable value transparently
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
        elif const.COMPILE_MODE == const.COMPILE_PRUNE:
            store.prune()
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
            item_path = path + dict_path.InDict(relation.name)
            match (current_value, previous_value):
                case None, None:
                    merged[relation.name] = None
                case None, dict():
                    # This is a deletion, recurse it
                    merged[relation.name] = merge_attributes(
                        previous_value,
                        previous_value,
                        operation=const.SLICE_DELETE,
                        path=item_path,
                        schema=relation.entity,
                    )
                case dict(), _:
                    merged[relation.name] = merge_attributes(
                        current_value,
                        previous_value,
                        operation=(
                            operation
                            if operation == const.SLICE_DELETE
                            else (
                                const.SLICE_CREATE
                                if previous_value is None
                                else const.SLICE_UPDATE
                            )
                        ),
                        path=item_path,
                        schema=relation.entity,
                    )
                case _:
                    raise ValueError()
            continue

        # Relation, attribute should be a list, and should be merged
        current_values = {
            relation.entity.instance_identity(current_value): current_value
            for current_value in typing.cast(list[dict], current[relation.name])
        }
        previous_values = {
            relation.entity.instance_identity(previous_value): previous_value
            for previous_value in typing.cast(
                list[dict], previous[relation.name] if previous is not None else []
            )
        }

        # Gather the identities of all the previous and current embedded entities
        # without losing the order
        all_identities = [
            relation.entity.instance_identity(current_value)
            for current_value in typing.cast(list[dict], current[relation.name])
        ]
        if previous is not None:
            all_identities.extend(
                [
                    identity
                    for previous_value in typing.cast(
                        list[dict], previous[relation.name]
                    )
                    if (identity := relation.entity.instance_identity(previous_value))
                    not in current_values
                ]
            )

        merged_relation: list[dict] = []
        merged[relation.name] = merged_relation
        for key in all_identities:
            current_value = current_values.get(key)
            previous_value = previous_values.get(key)
            item_path = path + dict_path.KeyedList(relation.name, key)
            match (current_value, previous_value):
                case None, dict():
                    # This is a deletion, recurse it
                    merged_relation.append(
                        merge_attributes(
                            previous_value,
                            previous_value,
                            operation=const.SLICE_DELETE,
                            path=item_path,
                            schema=relation.entity,
                        )
                    )
                case dict(), _:
                    merged_relation.append(
                        merge_attributes(
                            current_value,
                            previous_value,
                            operation=(
                                operation
                                if operation == const.SLICE_DELETE
                                else (
                                    const.SLICE_CREATE
                                    if previous_value is None
                                    else const.SLICE_UPDATE
                                )
                            ),
                            path=item_path,
                            schema=relation.entity,
                        )
                    )
                case _:
                    raise ValueError()

    return merged
