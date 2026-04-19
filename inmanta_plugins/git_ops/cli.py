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

import importlib
import pathlib

import click

from inmanta.module import ModuleV2
from inmanta_plugins.git_ops.generator import get_entity, get_module_builder
from inmanta_plugins.git_ops.store import SLICE_STORE_REGISTRY


@click.group()
def cli() -> None:
    """
    GitOps CLI group.
    """
    pass


@cli.command("generate")
@click.argument("module_path", type=click.Path(exists=True, file_okay=False))
def generate(module_path: str) -> None:
    """
    Generate the model for the slices defined in the input module.
    """
    module = ModuleV2.from_path(module_path)
    if module is None:
        raise click.BadParameter(f"Could not load module from path {module_path}")

    # The generator needs the module to be marked as editable
    module._is_editable_install = True

    for file in pathlib.Path(module.get_plugin_dir()).rglob("*.py"):
        # For each python file in the module, try to import it to load the slice definitions
        relative_path = file.relative_to(module.get_plugin_dir())
        module_name = relative_path.with_suffix("").as_posix().replace("/", ".")
        importlib.import_module(f"inmanta_plugins.{module.name}.{module_name}")

    builder = get_module_builder(module.name)

    # Collect the schema for all registered slice stores and generate the corresponding entities
    slices = [store.schema.entity_schema() for store in SLICE_STORE_REGISTRY.values()]
    [get_entity(s, slice_root=True) for s in slices]

    builder.upgrade_existing_module(module, fix_linting=False)


if __name__ == "__main__":
    cli()
