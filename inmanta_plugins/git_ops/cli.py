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
import logging
import os
import pathlib
import subprocess

import click
import texttable

from inmanta.module import ModuleV2, Project
from inmanta_plugins.git_ops import const
from inmanta_plugins.git_ops.store import SLICE_STORE_REGISTRY

LOGGER = logging.getLogger(__name__)


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
)
def cli(log_level: str) -> None:
    """
    Inmanta module git_ops CLI tool.
    """
    logging.basicConfig(level=log_level)


MODULE: ModuleV2 | None = None


@cli.group("module")
@click.option(
    "--module-path",
    type=click.Path(exists=True, file_okay=False),
    help="Path to the module to operate on.",
    envvar="INMANTA_GIT_OPS_MODULE_PATH",
    default=".",
    show_default=True,
    show_envvar=True,
)
def module(module_path: str, ) -> None:
    """
    Commands to manage the module containing slice definitions.
    """

    global MODULE
    MODULE = ModuleV2.from_path(module_path)
    if MODULE is None:
        raise click.BadParameter(f"Could not load module from path {module_path}")

    # The generator needs the module to be marked as editable
    MODULE._is_editable_install = True
    LOGGER.debug("Found module %s at path %s", MODULE.name, MODULE._path)

    for file in pathlib.Path(MODULE.get_plugin_dir()).rglob("*.py"):
        # For each python file in the module, try to import it to load the slice definitions
        relative_path = file.relative_to(MODULE.get_plugin_dir())
        module_name = f"inmanta_plugins.{MODULE.name}." + relative_path.with_suffix(
            ""
        ).as_posix().replace("/", ".")
        LOGGER.debug(f"Importing module {module_name} from {file}")
        importlib.import_module(module_name)


@module.command("generate")
@click.option(
    "--explicit-parent-relations",
    is_flag=True,
    help="Whether to generate explicit parent relations in the model.",
    envvar="INMANTA_GIT_OPS_EXPLICIT_PARENT_RELATIONS",
    default=False,
    show_envvar=True,
)
def generate(explicit_parent_relations: bool) -> None:
    """
    Generate the model for the slices defined in the input module.
    """
    from inmanta_plugins.git_ops import generator

    if explicit_parent_relations:
        generator.EXPLICIT_PARENT_RELATIONS = True

    assert MODULE is not None
    builder = generator.get_module_builder(MODULE.name)

    # Collect the schema for all registered slice stores and generate the corresponding entities
    slices = [store.schema.entity_schema() for store in SLICE_STORE_REGISTRY.values()]
    [generator.get_entity(s, slice_root=True) for s in slices]

    builder.upgrade_existing_module(MODULE, fix_linting=False)


@module.group("store")
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


PROJECT: Project | None = None
INMANTA_ARGS: list[str] = []


@cli.group("project")
@click.option("--inmanta-arg", multiple=True, help="Additional arguments to pass to the inmanta command.")
def project(inmanta_arg: list[str]) -> None:
    """
    Commands to manage the current Inmanta project.
    """
    global PROJECT
    PROJECT = Project.get()

    INMANTA_ARGS.extend(inmanta_arg)


@project.command("update")
@click.option("--inmanta-compile-arg", multiple=True, help="Additional arguments to pass to the inmanta compile command.")
def update(inmanta_compile_arg: list[str]) -> None:
    """
    Update the slice store with all active slices which have a more recent version
    or which are deleted.
    """
    # To figure out the stores used in the project, we need to run a compile
    # with all stores disabled, and then check which stores are used in the model.
    subprocess.run(
        ["inmanta", *INMANTA_ARGS, "compile", *inmanta_compile_arg],
        check=True,
        env={**os.environ, "INMANTA_GIT_OPS_COMPILE_MODE": const.COMPILE_UPDATE},
    )


@project.command("sync")
@click.option("--inmanta-compile-arg", multiple=True, help="Additional arguments to pass to the inmanta compile command.")
def sync(inmanta_compile_arg: list[str]) -> None:
    """
    Sync the slice store with all active slices which have a more recent version
    or which are deleted.
    """
    # To figure out the stores used in the project, we need to run a compile
    # with all stores disabled, and then check which stores are used in the model.
    subprocess.run(
        ["inmanta", *INMANTA_ARGS, "compile", *inmanta_compile_arg],
        check=True,
        env={**os.environ, "INMANTA_GIT_OPS_COMPILE_MODE": const.COMPILE_SYNC},
    )


@project.command("prune")
@click.option("--inmanta-compile-arg", multiple=True, help="Additional arguments to pass to the inmanta compile command.")
def prune(inmanta_compile_arg: list[str]) -> None:
    """
    Prune the slice store from all active slices which have a more recent version
    or which are deleted.
    """
    # To figure out the stores used in the project, we need to run a compile
    # with all stores disabled, and then check which stores are used in the model.
    subprocess.run(
        ["inmanta", *INMANTA_ARGS, "compile", *inmanta_compile_arg],
        check=True,
        env={**os.environ, "INMANTA_GIT_OPS_COMPILE_MODE": const.COMPILE_PRUNE},
    )



if __name__ == "__main__":
    cli()
