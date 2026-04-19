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
from inmanta_plugins.config.const import InmantaPath, InmantaTemplatePath


class SliceConfig(pydantic.BaseModel):
    """
    Configuration for a slice.
    """

    store_name: str = pydantic.Field(
        description="The name of the store to use for this slice.",
    )

    schema_path: InmantaPath | None = pydantic.Field(
        default=None,
        description=(
            "The path to the schema file for this slice.  "
            "When this is set, the schema will be updated every time the slices of this type are updated.",
        ),
    )

    parent_relation_name: InmantaTemplatePath | str = pydantic.Field(
        default="parent",
        description="The name of the relation to the parent entity of any embedded slice.",
    )


class GitOpsConfig(ConfigABC):
    """
    Configuration for the git-ops module.
    """

    slices: list[SliceConfig] = pydantic.Field(
        default_factory=list,
        description="The slices to manage with git-ops.",
    )

    @classmethod
    def raw_config_path(cls) -> str:
        return "inmanta:///files/git-ops-config.yaml"
