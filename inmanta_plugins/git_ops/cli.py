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
import json
import pathlib

import click
import texttable

from inmanta.module import ModuleV2
from inmanta_plugins.git_ops.generator import get_entity, get_module_builder
from inmanta_plugins.git_ops.store import SLICE_STORE_REGISTRY

MODULE: ModuleV2 | None = None


@click.group()
@click.option(
    "--module-path",
    type=click.Path(exists=True, file_okay=False),
    help="Path to the module to operate on.",
    envvar="INMANTA_GIT_OPS_MODULE_PATH",
    default=".",
    show_default=True,
    show_envvar=True,
)
def cli(module_path: str) -> None:
    """
    GitOps CLI group.
    """
    global MODULE
    MODULE = ModuleV2.from_path(module_path)
    if MODULE is None:
        raise click.BadParameter(f"Could not load module from path {module_path}")

    # The generator needs the module to be marked as editable
    MODULE._is_editable_install = True

    for file in pathlib.Path(MODULE.get_plugin_dir()).rglob("*.py"):
        # For each python file in the module, try to import it to load the slice definitions
        relative_path = file.relative_to(MODULE.get_plugin_dir())
        module_name = relative_path.with_suffix("").as_posix().replace("/", ".")
        importlib.import_module(f"inmanta_plugins.{MODULE.name}.{module_name}")


@cli.command("generate")
def generate() -> None:
    """
    Generate the model for the slices defined in the input module.
    """
    assert MODULE is not None
    builder = get_module_builder(MODULE.name)

    # Collect the schema for all registered slice stores and generate the corresponding entities
    slices = [store.schema.entity_schema() for store in SLICE_STORE_REGISTRY.values()]
    [get_entity(s, slice_root=True) for s in slices]

    builder.upgrade_existing_module(MODULE, fix_linting=False)


@cli.group("store")
def store() -> None:
    """
    Commands to manage slice stores.
    """
    pass


@store.command("list")
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def list_stores(format: str) -> None:
    """
    List all registered slice stores.
    """
    if format == "json":
        stores = [
            {
                "name": store.name,
                "path": store._folder,
                "description": (store.schema.__doc__ or "").strip(),
                "python_type": f"{store.schema.__module__}.{store.schema.__name__}",
            }
            for store in SLICE_STORE_REGISTRY.values()
        ]
        click.echo(json.dumps(stores, indent=2))
        return

    elif format == "table":
        table = texttable.Texttable()
        table.header(["Name", "Path", "Description"])

        for store in SLICE_STORE_REGISTRY.values():
            description = store.schema.__doc__ or ""
            description = description.strip().split("\n")[
                0
            ]  # Get the first line of the docstring
            table.add_row([store.name, store._folder, description])

        click.echo(table.draw())

    else:
        raise click.BadParameter(f"Unsupported format {format}")


@store.command("schema")
@click.option(
    "--store",
    type=str,
    required=True,
    help="The name of the store to get the schema for.",
)
def schema(store: str) -> None:
    """
    Print the JSON schema for the given store.
    """
    if store not in SLICE_STORE_REGISTRY:
        raise click.BadParameter(f"Store {store} is not registered")

    schema = SLICE_STORE_REGISTRY[store].schema
    click.echo(json.dumps(schema.model_json_schema(), indent=2))


if __name__ == "__main__":
    cli()
