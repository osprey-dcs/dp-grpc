# Generating and Importing Python Stubs

This repo defines the MLDP gRPC protocol and builds **Java** stubs.  Python stubs are generated
from the same `.proto` files and published through
[dp-python-lib](https://github.com/osprey-dcs/dp-python-lib).

> **Most Python users should not need this page.**  Install `dp-python-lib` and use its client
> classes, which wrap the raw stubs with Python-friendly request builders and result objects.
> Its [cookbook](https://github.com/osprey-dcs/dp-python-lib/tree/main/doc/cookbook) is the Python
> counterpart to this one, covering client construction, PV metadata, machine configuration, and
> querying into pandas / NumPy.
>
> This page is for readers who need to work with the generated protobuf modules directly, or who
> want to understand how the stubs are produced.

## How Python stubs are published

The [`generate-python-stubs.yml`](../../.github/workflows/generate-python-stubs.yml) workflow in
this repo runs on every `rel-*` tag (and on manual dispatch).  It:

1. Runs `grpc_tools.protoc` over `src/main/proto/*.proto`, emitting both the runtime modules
   (`*_pb2.py`, `*_pb2_grpc.py`) and [mypy-protobuf](https://github.com/nipunn1313/mypy-protobuf)
   type stubs for them (`*_pb2.pyi`, `*_pb2_grpc.pyi`)
2. Rewrites the generated absolute imports to relative ones, in the stubs as well as the modules,
   and fails if any absolute import survives or any module lacks a stub
3. Copies the result into `dp-python-lib` at `src/dp_python_lib/grpc/`
4. Opens a pull request against `dp-python-lib`

Every run, including a dry run, also attaches the generated tree to the workflow run as the
`python-stubs` artifact.

**`dp-python-lib` version *N* contains the stubs from dp-grpc `rel-N`**.  If you are running
dp-grpc 1.14.0, `dp-python-lib` 1.14.0 has the matching message definitions.

That correspondence is a release-process convention, not something this workflow enforces.
`dp-python-lib` derives its own version from its own git tag via setuptools-scm, so the sync PR
carries only regenerated stubs; the versions line up because `dp-python-lib` is tagged `rel-N`
once that PR merges.  See its `CLAUDE.md` ("Cutting a release").  A sync PR that has been opened
but not yet merged and tagged is the window where the two repos disagree.

## Importing the published stubs

Generated modules land flat under `dp_python_lib.grpc`, one pair per proto file:

```python
from dp_python_lib.grpc import annotation_pb2, annotation_pb2_grpc
from dp_python_lib.grpc import common_pb2
from dp_python_lib.grpc import query_pb2, query_pb2_grpc
from dp_python_lib.grpc import ingestion_pb2, ingestion_pb2_grpc
from dp_python_lib.grpc import ingestion_stream_pb2, ingestion_stream_pb2_grpc
```

The `*_pb2` modules contain the message types; the `*_pb2_grpc` modules contain the service stubs.
Each module has a `.pyi` type stub beside it; see [Type checking](#type-checking).

Messages defined in `common.proto` — `Timestamp`, `Attribute`, `Configuration`,
`ConfigurationActivation`, `DataBucket`, the column types — are in `common_pb2`, and
service-specific messages are in the module matching their proto file.  This mirrors the Java
package split described in the [main README](../../README.md#data-platform-grpc-api-proto-files).

## Generating stubs yourself

To generate stubs from a checkout of this repo without going through `dp-python-lib`:

```bash
pip install --require-hashes -r tools/python-stubs-requirements.txt

mkdir -p out/python
python -m grpc_tools.protoc \
    -I src/main/proto \
    --python_out=out/python \
    --grpc_python_out=out/python \
    --mypy_out=out/python \
    --mypy_grpc_out=out/python \
    src/main/proto/*.proto
```

That requirements file is the one the workflow installs from.  It pins the generators
(`grpcio-tools` and `mypy-protobuf`) and locks every transitive package by hash, so a local run
produces the same output as a release.  The `--mypy_out` / `--mypy_grpc_out` flags need
mypy-protobuf's `protoc-gen-mypy` plugins on `PATH`, which they are when the virtualenv they were
installed into is active.  Drop those two flags if you want only the runtime modules.

### The import fixup

`grpc_tools.protoc` emits absolute imports between generated modules — `import common_pb2 as ...`
— which only resolve if the output directory is itself on `sys.path`.  To use the output as a
package, rewrite them as relative imports.  The workflow does this with:

```bash
find out/python \( -name "*_pb2*.py" -o -name "*_pb2*.pyi" \) -exec \
    sed -i 's/^import \(.*_pb2\) as/from . import \1 as/' {} \;
```

The `.pyi` stubs need the same rewrite.  Missing it there fails nothing at runtime: the type
checker simply cannot resolve the import, and every type that crosses it degrades to `Any`
without an error.

On macOS, `sed -i` requires an argument: use `sed -i ''` or install GNU sed.

If you skip this step you will see `ModuleNotFoundError: No module named 'common_pb2'` when
importing any module that depends on `common.proto` — which is all of them.

## Type checking

The `.pyi` stubs are read only by type checkers such as mypy and pyright.  They add no runtime
dependency, and the `.py` modules are unchanged by them.

- **`*_pb2.pyi` types the messages**: constructors, fields, and enums.  A misspelled field, a
  field that does not exist, or a value of the wrong type is reported.  Enums are distinct types
  (`Foo.ValueType`), so passing one enum's value where another is expected is an error too.
- **`*_pb2_grpc.pyi` types the service stubs**, so that each RPC checks its request type and
  returns its response type.  This works only with
  [`types-grpcio`](https://pypi.org/project/types-grpcio/) installed.  Without it, `grpc`
  resolves to `Any`, stub calls go unchecked, and mypy reports `overload-cannot-match` inside the
  generated `*_pb2_grpc.pyi` itself.
- **A stub held in an `Any`-typed variable is not checked at all.**  Annotate it with the
  generated class, for example `stub: query_pb2_grpc.DpQueryServiceStub`, or let its type be
  inferred from the constructor call.

## Version compatibility

The MLDP API is additive across releases: new fields and methods are added, existing field
numbers are not reused or repurposed.  Stubs generated from a newer dp-grpc release will
generally interoperate with an older server, and vice versa, with unknown fields ignored.

That said, a client calling a method the deployed server does not implement will get an error
response.  The cookbook recipes track the current release, so if you are running an older server,
check the method against the [README](../../README.md) before relying on it.
