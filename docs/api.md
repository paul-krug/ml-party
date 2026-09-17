# API reference

The public Python surface. The in-process client is what training scripts
use; `MlParty` is the core API every frontend (MCP, CLI, HTTP) is a thin
layer over; the models are the ontology.

## Client (training scripts)

```{eval-rst}
.. automodule:: mlparty.client
   :members: attach, start_run, RunHandle
```

## Core

```{eval-rst}
.. autoclass:: mlparty.core.MlParty
   :members:
   :undoc-members:
```

## Run control

```{eval-rst}
.. automodule:: mlparty.actions
   :members: ActionTemplate, ActionParam
   :undoc-members:
```

## Ontology models

```{eval-rst}
.. automodule:: mlparty.models
   :members: Edge, Abstract, Result, Failure, RunNode, ExperimentNode,
             ProjectNode, NoteNode, ArtifactRef, DataRef, Hardware,
             ComputeRef, Invocation, SnapshotReport
   :undoc-members:
```
