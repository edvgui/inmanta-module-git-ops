"""
Copyright 2026 Guillaume Everarts de Velp

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

import uuid
import typing
import pathlib
import pytest
from pytest_inmanta.plugin import Project
from inmanta_plugins.git_ops import const, store, slice


class GitOpsProject:
    """
    Helper class to interact with a git-ops project in a pytest test suite.
    """

    def __init__(self, environment: uuid.UUID, project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
        self.environment = environment
        self.project = project
        self.monkeypatch = monkeypatch
        self.model: str | None = None
        self.stores: dict[str, store.SliceStore] | None = None

    def load_stores(self, model: str) -> None:
        """
        Perform an empty compile on the given model, and register any slice store
        that comes out of it.  The model also becomes the default model for all
        later compiles.
        """
        with self.monkeypatch.context() as ctx:
            ctx.setattr(const, "COMPILE_MODE", const.COMPILE_EMPTY)
            self.project.compile(self._model(model))

        self.stores = dict(store.SLICE_STORE_REGISTRY)
        self.model = model

    def _model(self, model: str | None = None) -> str:
        """
        Helper method to resolve the model that should be used in a compile.
        If a model is provided in argument, use it, otherwise default to the
        cached model (self.model).  If no cached model exists, raise an
        exception.
        """
        if model is not None:
            return model

        if self.model is not None:
            return self.model

        raise ValueError("No model to compile!")

    @typing.overload
    def get_store(self, store_name: str, slice: None = None) -> store.SliceStore:
        pass

    @typing.overload
    def get_store[S: slice.SliceObjectABC](
        self,
        store_name: str,
        slice: S,
    ) -> store.SliceStore[S]:
        pass

    def get_store[S: slice.SliceObjectABC](
        self,
        store_name: str,
        slice: S | None = None,
    ) -> store.SliceStore[S] | store.SliceStore:
        """
        Get the store with the given name.

        :param store_name: The name of the store to fetch.
        :param slice: When provided, validates that the resolved store accepts slices of the given type.
        """
        if self.stores is None:
            raise RuntimeError("No stores have been loaded, call self.load_stores()")

        if store_name not in self.stores:
            raise LookupError(f"No store named {store_name} in project.  Available stores are: {list(self.stores)}")

        slice_store = self.stores[store_name]

        if slice is None:
            return slice_store

        # Validate that the schema of the store matches the type
        # of the slice
        if slice_store.schema is not type(slice):
            raise RuntimeError(
                f"Invalid slice store for slice {slice}: {store_name} has schema {slice_store.schema}"
            )

        return slice_store

    def slice_name(self, s: slice.SliceObjectABC) -> str:
        """
        Generate a stable name for the given slice object, based on the keys attribute
        of the slice.
        """
        return str(uuid.uuid5(self.environment, "-".join(getattr(s, k) for k in type(s).keys)))

    def get_slice_source(self, store_name: str, slice_name: str) -> store.SliceFile:
        """
        Get the path in which the given named slice is defined.  This is the
        path to the editable version of the slice (in the source store).

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        # First find the store in which the slice belongs
        slice_store = self.get_store(store_name)
        slice_path = slice_store.source_path / (slice_name + ".json")
        slice_path.parent.mkdir(parents=True, exist_ok=True)

        return store.SliceFile(
            path=slice_path,
            name=slice_name,
            version=None,
            extension="json",
            schema=slice_store.schema,
        )

    def get_slice_versions(self, store_name: str, slice_name: str) -> list[store.SliceFile]:
        """
        Get the list of all known slice versions for the given store and slice name.

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        # First find the store in which the slice belongs
        slice_store = self.get_store(store_name)
        slice_files = [
            store.SliceFile.from_path(path, slice_store.schema)
            for path in slice_store.active_path.glob(f"{slice_name}@v*.json")
        ]
        return sorted(slice_files, key=lambda f: f.version or 0)

    def write_slice(
        self,
        store_name: str,
        slice_name: str,
        s: slice.SliceObjectABC,
        *,
        update: bool = True,
        sync: bool = True,
        model: str | None = None,
    ) -> store.SliceFile:
        """
        Write the given slice in a dedicated file in the appropriate source slice folder.
        Before calling this method you must call self.load_stores() so we can find the
        store in which this slice belongs.

        When the slice is written to file, update and sync compiles can also be triggered
        automatically to validate and persist the change.

        This method returns a SliceFile object pointing to the slice where the slice
        has been written.  If sync is True, the file is the commited version of the
        slice (active store) otherwise it is the editable one (source store).

        :param s: The slice to write to file.
        :param update: Whether an update compile should be triggered.
        :param sync: Whether a sync compile should be triggered.
        :param name: An arbitrary name to give to the slice, if none is provided, a name
            is derived based on the identifying keys of the slice.
        :param model: The model to use in the compiles.
        """
        # Create the source slice file object
        slice_file = self.get_slice_source(store_name, slice_name)

        # Write the slice to source slice file
        slice_file.write(s.model_dump(mode="json"))

        if update:
            # Trigger updating compile
            self.update(model)

        if sync:
            # Trigger syncing compile
            self.sync(model)
            slice_file = self.get_slice_versions(store_name, slice_name)[-1]

        return slice_file

    def remove_slice(self, store_name: str, slice_name: str) -> store.SliceFile:
        """
        Get the path in which the given slice is defined, and make sure it
        doesn't exist.  Return the corresponding slice file object.

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        slice_file = self.get_slice_source(store_name, slice_name)
        slice_file.path.unlink(missing_ok=True)
        return slice_file

    def update(self, model: str | None = None) -> None:
        """
        Run an updating compile on the current project.
        """
        with self.monkeypatch.context() as ctx:
            ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
            self.project.compile(self._model(model))

    def sync(self, model: str | None = None) -> None:
        """
        Run a synchronizing compile on the current project.
        """
        with self.monkeypatch.context() as ctx:
            ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
            self.project.compile(self._model(model))

    def export(self, model: str | None = None) -> None:
        """
        Run an exporting compile on the current project.  No resources are
        exported to any available server, but resources are serialized.
        """
        with self.monkeypatch.context() as ctx:
            ctx.setattr(const, "COMPILE_MODE", const.COMPILE_EXPORT)
            self.project.compile(self._model(model))

    def prune(self, model: str | None = None) -> None:
        """
        Run a pruning compile on the current project.  Don't unroll any
        service, but cleanup any old version of slices present in the
        project.
        """
        with self.monkeypatch.context() as ctx:
            ctx.setattr(const, "COMPILE_MODE", const.COMPILE_PRUNE)
            self.project.compile(self._model(model))
