# GitOps module

## Key concepts

This module allows to easily parameterize a model by defining and exposing slices.
These slices can be instantiated by adding files in the project using the module.
Each slice instance will be a json or yaml file, that the end user can edit.
Changes made to the slices should be committed in a dedicated branch, then merged into master.
The master branch of the project can then be pulled in the orchestrator to deploy the changes.

### Multi-store

Slices are stored in two different places in the project:
1. The **source** slices are user owned, located in the folder that the user picked when constructing the SliceStore.  The user can created, update and delete these slices.  The compile may also update these slices using specific plugins.
2. The **active** slices are read-only to the user, located in a fixed folder in the project.  The contain the version of the slices that have been already updated and activated by the user.  Each slice is versioned, and can have more than one file in that folder, one for each active version.

**Example project layout**:
TODO

### Multi-compiles

Projects which are using this module can do three types of compile:
1. **update**: These compiles read the slice sources provided by the user, and let the compile process complete the information available in these slices.  This compile can be repeated as many times as required, until the slices have all the information they need.
2. **sync**: Read the slice sources, make sure that a compile doesn't trigger any change on them, then persist these slices into the active store.
3. **export** (default): Read the slices from the active store, and export resources based on them.

The end user workflow when creating changes is then:
1. Checkout out a new branch.
2. Manually modify/create/delete one or more slices in the source folders.
3. Run the **update** compile.
4. If the outcome of the **update** compile is not what the end user wanted, go back to 2.
5. Confirm the update using the **sync** compile.
6. (Optional) Push the branch to the remote repo, run ci, get reviews, etc.
7. Merge the branch into master.
8. Update and recompile on the orchestrator to get the latest version of the project.  (**export** compile done by the orchestrator)

### Multi-version

In order to keep track of deleted items in a service, the slices emitted in the model don't limit themselves to the attributes contained in the source slice files.  The active store can contain multiple versions of a slice, which allows us to compare the latest version with the previous, and see which elements where deleted.  When a piece of a slice is deleted from the source file, it will be available in the model still, marked as `purged`.  This allows the model to purge the related resources, making sure the automation doesn't leave anything behind.
