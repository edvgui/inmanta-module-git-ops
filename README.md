# GitOps module

[![pypi version](https://img.shields.io/pypi/v/inmanta-module-git-ops.svg)](https://pypi.python.org/pypi/inmanta-module-git-ops/)
[![build status](https://img.shields.io/github/actions/workflow/status/edvgui/inmanta-module-git-ops/continuous-integration.yml)](https://github.com/edvgui/inmanta-module-git-ops/actions)

This package is an integration module that is meant to be used with the inmanta orchestrator: https://docs.inmanta.com

It allows you to easily parametrize a model by defining slices, and then instantiating as many slices as you need to by simply creating json or yaml files in the project repository.  This module aims at enabling its users to manage an infra in a "Git-Ops" fashion.  Key ideas are:
1. Declarative Configuration: The desired state of your infrastructure and applications is described in a declarative format (json/yaml files) within a Git repository. 
2. Version Control: Git serves as the central source of truth, meaning all changes are committed to the repository, providing a complete history of the system's evolution. 
3. Automated Synchronization: The orchestrator continuously monitors the Git repository and pulls in new updates. 
4. Pull Requests for Changes: When you want to make a change, you create a pull request to modify the Git repository. 
5. Deployment & Reconciliation: Once the pull request is approved and merged, the orchestrator automatically pulls the changes and deploys them to the live environment, ensuring the actual system state matches the desired state in Git.

All of this is already natively supported by the orchestrator by modifying the `main.cf` file of a project.  This works but scales poorly and it is not possible to track deleted items, this modules aims at addressing these limitations.

More details about the design in the [docs](docs/) folder.

## Cli

This module also provides a cli interface, to facilitate the creation of a module based on git_ops and the management of a project using git_ops.

If the module is installed in your venv, just run the `git-ops` command.

```console
$ git-ops --help
Usage: git-ops [OPTIONS] COMMAND [ARGS]...

  Inmanta module git_ops CLI tool.

Options:
  --log-level [DEBUG|INFO|WARNING|ERROR]
  --help                          Show this message and exit.

Commands:
  module   Commands to manage the module containing slice definitions.
  project  Commands to manage the current Inmanta project.
```


## Running tests

1. Set up a new virtual environment, then install the module in it. The first line assumes you have ``virtualenvwrapper``
installed. If you don't, you can replace it with `python3 -m venv .env && source .env/bin/activate`.

```bash
mkvirtualenv inmanta-test -p python3 -a .
pip install -e . -c requirements.txt -r requirements.dev.txt
```

2. Run tests

```bash
pytest tests
```
