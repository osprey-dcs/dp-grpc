#!/usr/bin/env python3
"""Compile every ```java block in doc/cookbook/ against the generated gRPC stubs.

Cookbook snippets are fragments, not programs: they reference undeclared locals
(`response`, `stub`) and shorthand helpers (`ts(...)`). This wraps each block in a
class with wildcard imports, that document's own imports block, and stubs for the
helpers, then compiles the lot.

What the results mean:

  unresolved TYPE      a real bug -- the class does not exist, or is nested and the
                       recipe gave no import for it
  unresolved VARIABLE  expected -- the snippet is a fragment
  unresolved MEMBER    a real bug -- a method or field on a generated class that does
                       not exist, e.g. a misspelled setter
  syntax error         a real bug -- the snippet is not valid Java

Exits non-zero if any of the real bugs above is found, if no snippets were extracted,
or if javac fails in a way this script does not recognize. CI runs it on every pull
request and push to main (.github/workflows/ci.yml); run it locally before pushing
for a faster loop.

Usage:
    mvn compile                                  # generate and compile the stubs first
    python3 tools/check-cookbook-snippets.py     # check all recipes
    python3 tools/check-cookbook-snippets.py --keep /tmp/snips   # retain generated sources
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DOCS = REPO / 'doc' / 'cookbook'
CLASSES = REPO / 'target' / 'classes'

# Wildcard imports covering every generated package plus common grpc/java types.
# NOTE: com.google.protobuf.* is deliberately NOT wildcarded -- it defines its own
# Timestamp, which collides with com.ospreydcs.dp.grpc.v1.common.Timestamp.
PREAMBLE = """
import com.ospreydcs.dp.grpc.v1.common.*;
import com.ospreydcs.dp.grpc.v1.query.*;
import com.ospreydcs.dp.grpc.v1.annotation.*;
import com.ospreydcs.dp.grpc.v1.ingestion.*;
import com.ospreydcs.dp.grpc.v1.ingestionstream.*;
import io.grpc.*;
import io.grpc.stub.*;
import com.google.protobuf.ByteString;
import java.util.*;
import java.util.concurrent.*;
"""

# Shorthand the recipes use by convention rather than spelling out. Keep in sync
# with what the cookbook actually writes; an unresolved *variable* is tolerated,
# so this only needs to cover helpers whose absence would be confusing.
TS = 'com.ospreydcs.dp.grpc.v1.common.Timestamp'
HELPERS = f"""
  static {TS} ts(Object o) {{ return {TS}.newBuilder().build(); }}
  static {TS} ts(long a, long b) {{ return {TS}.newBuilder().build(); }}
  static long now = 0L, oneDayAgo = 0L, t0 = 0L, t1 = 0L, beginNanos = 0L, endNanos = 0L;
  static String pageToken = "", providerId = "", pvName = "", clientActivationId = "";
  static String dataSetId = "", annotationId = "", configurationName = "";
  static void process(Object o) {{}}
  static void fail(String s) {{}}
"""

BLOCK_RE = re.compile(r'```java\n(.*?)```', re.S)

# A snippet that deliberately will not compile -- a placeholder type standing in for
# something the caller supplies, or an interface with methods elided -- opts out with
# a marker comment. Keep these rare and always visible to the reader.
#   // cookbook:partial <reason>
PARTIAL_RE = re.compile(r'//\s*cookbook:partial\b')


def extract(out_dir):
    """Write one wrapped .java file per cookbook snippet. Returns the manifest."""
    if not DOCS.is_dir():
        sys.exit(f"error: {DOCS} not found")

    manifest = []
    for md in sorted(DOCS.glob('*.md')):
        text = md.read_text()
        blocks = [(m.group(1), text[:m.start()].count('\n') + 2)
                  for m in BLOCK_RE.finditer(text)]

        # A recipe's own imports block resolves the nested types it uses, so feed
        # it to every snippet from that document.
        doc_imports = sorted({
            line.strip()
            for code, _ in blocks
            for line in code.splitlines()
            if line.strip().startswith('import ')
        })

        for code, line in blocks:
            only_imports = all(
                (not l.strip()) or l.strip().startswith(('import ', '//'))
                for l in code.splitlines()
            )
            cls = f"Snip{len(manifest):03d}"
            imports = code if only_imports else "\n".join(doc_imports)
            body = "" if only_imports else code

            (out_dir / f"{cls}.java").write_text(
                f"{imports}\n{PREAMBLE}\n"
                f'@SuppressWarnings("all")\n'
                f"public class {cls} {{\n{HELPERS}\n"
                f"  static void body() throws Exception {{\n{body}\n  }}\n}}\n"
            )
            manifest.append({'class': cls, 'doc': md.name, 'line': line,
                             'partial': PARTIAL_RE.search(code) is not None})

    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    return manifest


def classpath():
    """target/classes plus the Maven dependency classpath."""
    if not CLASSES.is_dir():
        sys.exit("error: target/classes not found -- run 'mvn compile' first")

    cp_file = REPO / 'target' / 'cookbook-cp.txt'
    if not cp_file.exists():
        print("resolving dependency classpath...")
        r = subprocess.run(
            ['mvn', '-q', 'dependency:build-classpath',
             f'-Dmdep.outputFile={cp_file}'],
            cwd=REPO, capture_output=True, text=True,
        )
        if r.returncode != 0 or not cp_file.exists():
            sys.exit(f"error: could not resolve classpath\n{r.stdout}\n{r.stderr}")
    return f"{CLASSES}:{cp_file.read_text().strip()}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', metavar='DIR',
                    help='write generated sources here and keep them')
    args = ap.parse_args()

    out_dir = pathlib.Path(args.keep) if args.keep else pathlib.Path(tempfile.mkdtemp())
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = extract(out_dir)
        docs = len({e['doc'] for e in manifest})
        print(f"extracted {len(manifest)} java blocks from {docs} docs")
        # Zero blocks means the extraction broke (a moved directory, a changed fence
        # style), not that the cookbook is clean. Passing here would disarm the gate.
        if not manifest:
            print(f"error: no ```java blocks found in {DOCS}")
            return 1

        classes_out = out_dir / '_classes'
        classes_out.mkdir(exist_ok=True)
        r = subprocess.run(
            ['javac', '-nowarn', '-Xmaxerrs', '10000', '-d', str(classes_out),
             '-cp', classpath()] + [str(p) for p in sorted(out_dir.glob('Snip*.java'))],
            capture_output=True, text=True,
        )

        by_class = {e['class']: e for e in manifest}
        lines = r.stderr.splitlines()
        real, partial, parsed = [], 0, 0
        for i, line in enumerate(lines):
            m = re.match(r'.*/(Snip\d+)\.java:(\d+): error: (.*)', line)
            if not m:
                continue
            parsed += 1
            cls, msg = m.group(1), m.group(3)
            # javac follows each error with the offending source line, a caret,
            # then "symbol:" / "location:". Scan ahead to the next error for both
            # rather than assuming a fixed offset.
            kind = name = location = None
            for f in lines[i + 1:]:
                if re.match(r'.*/Snip\d+\.java:\d+: error: ', f):
                    break
                if 'symbol:' in f:
                    parts = f.split('symbol:')[1].split()
                    kind = parts[0] if parts else None
                    name = parts[1] if len(parts) > 1 else None
                elif 'location:' in f:
                    location = f.split('location:')[1].strip()
            # Tolerate only what a fragment legitimately leaves undeclared: a local
            # or helper looked up in the snippet's own wrapper class. Two things
            # look similar and are real errors:
            #   - "location: class Builder" (or any class other than SnipNNN) means
            #     a member lookup on a real type failed -- a misspelled setter or
            #     getter, the drift a proto field rename causes.
            #   - javac reports an unknown *type* used as an expression receiver as
            #     "symbol: variable Foo", indistinguishable by kind from a local, so
            #     UpperCamelCase names are treated as type references.
            # javac omits "location:" for an unqualified name inside an anonymous
            # class (a StreamObserver in a snippet, say), which has no name to print.
            # A qualified member lookup always carries one, so absent means wrapper.
            in_wrapper = location is None or re.fullmatch(r'class Snip\d+', location)
            if (kind in ('variable', 'method') and 'cannot find symbol' in msg
                    and name and not name[0].isupper() and in_wrapper):
                continue  # expected: snippets are fragments
            e = by_class.get(cls, {})
            if e.get('partial'):
                partial += 1
                continue  # snippet is explicitly marked as not compilable
            detail = f" ({' '.join(filter(None, (kind, name)))})" if kind else ""
            if location and not in_wrapper:
                detail += f" in {location}"
            real.append(f"  {e.get('doc', cls)}:{e.get('line', '?')}  {msg}{detail}")

        # javac failed but reported nothing attributable to a snippet: a bad flag, an
        # unreadable classpath, no source files. Every error being filtered is fine;
        # a failure that was never parsed at all is not.
        if r.returncode != 0 and parsed == 0:
            print(f"\nerror: javac exited {r.returncode} without a snippet error:\n"
                  f"{r.stderr.strip()}")
            return 1

        if real:
            print(f"\n{len(real)} real problem(s):\n" + "\n".join(real))
            print("\n(unresolved locals and helpers in the snippet itself are "
                  "filtered out -- snippets are fragments; mark a deliberately "
                  "non-compiling snippet with '// cookbook:partial <reason>')")
            return 1

        note = f" ({partial} skipped in cookbook:partial snippets)" if partial else ""
        print(f"no unresolved types or members, and no syntax errors{note}")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
