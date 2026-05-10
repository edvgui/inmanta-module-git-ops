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

from inmanta_plugins.git_ops import slice, store


class GitOpsSlice[S: slice.SliceObjectABC]:
    """
    Helper class to interact with a git-ops project in a pytest test suite.
    """

    def __init__(
        self,
        slice_object: S,
        store_object: store.SliceStore[S],
        slice_name: str,
    ) -> None:
        self.slice = slice_object
        self.store = store_object
        self.name = slice_name

    def get_source(self) -> store.SliceFile:
        """
        Get the path in which the given named slice is defined.  This is the
        path to the editable version of the slice (in the source store).

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        # First find the store in which the slice belongs
        slice_path = self.store.source_path / (self.name + ".json")
        slice_path.parent.mkdir(parents=True, exist_ok=True)

        return store.SliceFile(
            path=slice_path,
            name=self.name,
            version=None,
            extension="json",
            schema=self.store.schema,
        )

    def get_versions(self) -> list[store.SliceFile]:
        """
        Get the list of all known slice versions for the given store and slice name.

        :param store_name: The name of the store in which the slice exists
        :param slice_name: The name of the slice within the store
        """
        # First find the store in which the slice belongs
        slice_files = [
            store.SliceFile.from_path(path, self.store.schema)
            for path in self.store.active_path.glob(f"{self.name}@v*.json")
        ]
        return sorted(slice_files, key=lambda f: f.version or 0)
