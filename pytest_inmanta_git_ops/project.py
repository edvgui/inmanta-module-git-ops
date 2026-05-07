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

    def write_slice(
        self,
        s: slice.SliceObjectABC,
        *,
        update: bool = True,
        sync: bool = True,
        name: str | None = None,
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
        # First fine the store in which the slice belongs
        if self.stores is None:
            raise RuntimeError("No stores have been loaded, call self.load_stores()")

        try:
            slice_store = next(
                slice_store
                for slice_store in self.stores.values()
                if slice_store.schema is type(s)
            )
        except StopIteration as e:
            raise RuntimeError(f"No store for slice {s} (type {type(s)}) in {list(self.stores)}") from e

        # Resolve the source slice path
        slice_name = name or str(uuid.uuid5(self.environment, "-".join(getattr(s, k) for k in type(s).keys)))
        slice_path = slice_store.source_path / (slice_name + ".json")
        slice_path.parent.mkdir(parents=True, exist_ok=True)

        # Create the source slice file object
        slice_file = store.SliceFile(
            path=slice_path,
            name=slice_name,
            version=None,
            extension="json",
            schema=type(s),
        )

        # Write the slice to source slice file
        slice_file.write(s.model_dump(mode="json"))

        if update:
            # Trigger updating compile
            self.update(model)

        if sync:
            # Trigger syncing compile
            self.sync(model)
            slice_files = [
                store.SliceFile.from_path(path, type(s))
                for path in slice_store.active_path.glob(f"{slice_name}@v*.json")
            ]
            slice_files = sorted(slice_files, key=lambda f: f.version or 0, reverse=True)
            slice_file = slice_files[0]

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
