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

import typing
import uuid

import pytest
from pytest_inmanta.plugin import Project

from inmanta.execute.proxy import DynamicProxy
from inmanta_plugins.git_ops import const, slice, store
from pytest_inmanta_git_ops.slice import GitOpsSlice


class GitOpsProject:
    """
    Helper class to interact with a git-ops project in a pytest test suite.
    """

    def __init__(
        self, environment: uuid.UUID, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
            raise LookupError(
                f"No store named {store_name} in project.  Available stores are: {list(self.stores)}"
            )

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
        return str(
            uuid.uuid5(self.environment, "-".join(getattr(s, k) for k in type(s).keys))
        )

    def test_slice[S: slice.SliceObjectABC](
        self,
        s: S,
        *,
        store_name: str,
        slice_name: str | None = None,
    ) -> GitOpsSlice[S]:
        """
        Construct a GitOpsSlice object to wrap a slice, and easily maniupulate it in the
        tests.
        """
        slice_store = self.get_store(store_name, slice=s)
        return GitOpsSlice(s, slice_store, slice_name or self.slice_name(s))

    def write_slice(
        self,
        s: GitOpsSlice,
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
        slice_file = s.get_source()

        # Write the slice to source slice file
        slice_file.write(s.slice.model_dump(mode="json"))

        if update:
            # Trigger updating compile
            self.update(model)

            # Refresh slice object with updated data
            s.slice = s.store.schema(**slice_file.read())

        if sync:
            # Trigger syncing compile
            self.sync(model)
            slice_file = s.get_versions()[-1]

        return slice_file

    def remove_slice(
        self,
        s: GitOpsSlice,
        *,
        update: bool = True,
        sync: bool = True,
        model: str | None = None,
    ) -> store.SliceFile:
        """
        Get the path in which the given slice is defined, and make sure it
        doesn't exist.  Return the corresponding slice file object.

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        slice_file = s.get_source()
        slice_file.delete()

        if update:
            # Trigger updating compile
            self.update(model)

        if sync:
            # Trigger syncing compile
            self.sync(model)
            slice_file = s.get_versions()[-1]

        return slice_file

    def get_instance(self, s: GitOpsSlice) -> DynamicProxy:
        """
        Try to get the instance of the given slice in the result of the latest compile.
        The returned object is the DynamicProxy instance matching the input slice that
        was created by unrolling the slice store in which our slice is defined.

        Raises a LookupError if no matching instance can be found.
        """
        for instance in self.project.get_instances("git_ops::slice::SliceObjectABC"):
            if instance.slice_store != s.store.name:
                continue

            if instance.slice_name != s.name:
                continue

            return instance

        raise LookupError(
            f"Couldn't find any slice named {s.name} in store {s.store.name} in latest compile"
        )

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
