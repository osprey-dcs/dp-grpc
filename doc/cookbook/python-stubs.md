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

1. Runs `grpc_tools.protoc` over `src/main/proto/*.proto`
2. Rewrites the generated absolute imports to relative ones
3. Copies the result into `dp-python-lib` at `src/dp_python_lib/grpc/`
4. On a release tag, sets the `dp-python-lib` version to match the dp-grpc release version
5. Opens a pull request against `dp-python-lib`

Because step 4 pins the versions together, **`dp-python-lib` version *N* contains the stubs from
dp-grpc `rel-N`**.  If you are running dp-grpc 1.14.0, `dp-python-lib` 1.14.0 has the matching
message definitions.

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

Messages defined in `common.proto` — `Timestamp`, `Attribute`, `Configuration`,
`ConfigurationActivation`, `DataBucket`, the column types — are in `common_pb2`, and
service-specific messages are in the module matching their proto file.  This mirrors the Java
package split described in the [main README](../../README.md#data-platform-grpc-api-proto-files).

## Generating stubs yourself

To generate stubs from a checkout of this repo without going through `dp-python-lib`:

```bash
pip install grpcio grpcio-tools protobuf

mkdir -p out/python
python -m grpc_tools.protoc \
    -I src/main/proto \
    --python_out=out/python \
    --grpc_python_out=out/python \
    src/main/proto/*.proto
```

### The import fixup

`grpc_tools.protoc` emits absolute imports between generated modules — `import common_pb2 as ...`
— which only resolve if the output directory is itself on `sys.path`.  To use the output as a
package, rewrite them as relative imports.  The workflow does this with:

```bash
find out/python -name "*_pb2*.py" -exec \
    sed -i 's/^import \(.*_pb2\) as/from . import \1 as/' {} \;
```

On macOS, `sed -i` requires an argument: use `sed -i ''` or install GNU sed.

If you skip this step you will see `ModuleNotFoundError: No module named 'common_pb2'` when
importing any module that depends on `common.proto` — which is all of them.

## Version compatibility

The MLDP API is additive across releases: new fields and methods are added, existing field
numbers are not reused or repurposed.  Stubs generated from a newer dp-grpc release will
generally interoperate with an older server, and vice versa, with unknown fields ignored.

That said, a client calling a method the deployed server does not implement will get an error
response — so when following a cookbook recipe, check its **Verified against** note against your
deployed version.
