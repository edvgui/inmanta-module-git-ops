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

import pydantic
from inmanta_plugins.config.abc import ConfigABC
from inmanta_plugins.config.const import InmantaPath, SystemPath


class SliceStoreConfig(pydantic.BaseModel):
    """
    Configuration for a slice store.
    """

    store_name: str = pydantic.Field(
        description="The name of the store to use for this slice.",
    )

    schema_path: InmantaPath | SystemPath | None = pydantic.Field(
        default=None,
        description=(
            "The path to the schema file for this slice.  "
            "When this is set, the schema will be updated every time the slices of this type are updated.",
        ),
    )

    @classmethod
    def get_for_store(cls, store_name: str) -> "SliceStoreConfig":
        """
        Get the configuration for a slice type.
        """
        try:
            # Try to load the config, if it doesn't exist, return a default config with the default store
            config = GitOpsConfig.load()
        except FileNotFoundError:
            return SliceStoreConfig(store_name="default")

        # Then try to find a config for this store, if it doesn't exist, return a default config with this store
        for store_config in config.stores:
            if store_config.store_name == store_name:
                return store_config

        return SliceStoreConfig(store_name="default")


class GitOpsConfig(ConfigABC):
    """
    Configuration for the git-ops module.
    """

    stores: list[SliceStoreConfig] = pydantic.Field(
        default_factory=list,
        description="The stores to manage with git-ops.",
    )

    @classmethod
    def raw_config_path(cls) -> str:
        return "inmanta:///files/git-ops-config.yml"
