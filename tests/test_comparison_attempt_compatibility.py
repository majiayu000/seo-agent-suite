"""Pinned, offline #57 no-option composition; no package limit option added."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "scripts/public_http.py": "fbccf869ddd56db35b9cdb064c191ba4fdce2f8a55cbc931c7e1b158bf7f89b1",
    "scripts/site_meta_audit.py": "dd5f6cd6ae01513d1cb71dbbd9d5aea64d46a6225d461f5f55a5ab3078d2ae96",
}


def apply_body_fixture(root, *, reverse=False):
    """Materialize one exact frozen Q5/P07 source pair, only in test scratch."""
    fixture = json.loads((ROOT / "tests/fixtures/comparison_metadata/q5-no-option.json").read_text())
    source, target = ("after", "before") if reverse else ("before", "after")
    for entry in fixture:
        assert entry["path"] in TARGETS
        path = root / entry["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == entry[target + "_sha256"]:
            continue
        assert digest == entry[source + "_sha256"], entry["path"]
        lines = path.read_text().splitlines(keepends=True)
        output, consumed = [], 0
        for hunk in entry["hunks"]:
            start = hunk[source + "_start"]
            old, new = hunk[source], hunk[target]
            assert lines[start:start + len(old)] == old
            output.extend(lines[consumed:start])
            output.extend(new)
            consumed = start + len(old)
        output.extend(lines[consumed:])
        path.write_text("".join(output))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry[target + "_sha256"]


@contextmanager
def composed_checkout():
    """Apply the reviewed historical fixture to disposable source, not a branch.

    The fixture preserves #38's bound DEFAULT_* references. Exact resulting
    file hashes prevent accidental context reconciliation or unsupported variants.
    Already-composed source must have those same reviewed bytes.
    """
    with tempfile.TemporaryDirectory(prefix="seo-p05-p07-") as directory:
        root = (Path(directory) / "suite").resolve()
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "build", "dist", "*.egg-info"))
        # Retain the historical P07 fixture even when the outer checkout has
        # the exact reviewed Q5 source. This is test materialization, not runtime
        # recognition: no unsupported or merely similar source is accepted.
        body_fixture = json.loads((ROOT / "tests/fixtures/comparison_metadata/q5-no-option.json").read_text())
        if all(hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
               == entry["after_sha256"] for entry in body_fixture):
            apply_body_fixture(root, reverse=True)
        lines = json.loads((ROOT / "tests/fixtures/comparison_metadata/pr57-no-option.patch.json").read_text())
        index = 0
        while index < len(lines):
            assert lines[index].startswith("--- a/")
            relative = lines[index][6:].strip()
            assert relative in TARGETS
            index += 2
            path = root / relative
            original = path.read_text().splitlines(keepends=True)
            already = hashlib.sha256(path.read_bytes()).hexdigest() == TARGETS[relative]
            output, consumed = [], 0
            while index < len(lines) and not lines[index].startswith("--- a/"):
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[index])
                assert match, lines[index]
                start = int(match.group(1)) - 1
                index += 1
                old, new = [], []
                while index < len(lines) and not lines[index].startswith(("@@", "--- a/")):
                    line = lines[index]
                    if line[0] in " -": old.append(line[1:])
                    if line[0] in " +": new.append(line[1:])
                    index += 1
                if not already:
                    assert original[start:start + len(old)] == old, relative
                    output.extend(original[consumed:start])
                    output.extend(new)
                    consumed = start + len(old)
            if not already:
                output.extend(original[consumed:])
                path.write_text("".join(output))
            assert hashlib.sha256(path.read_bytes()).hexdigest() == TARGETS[relative]
        # An inherited pip editable finder can otherwise map this package's
        # collectors back to the original checkout, despite the temporary src
        # path. Give this disposable package a concrete local collectors package
        # so normal package lookup wins over that external editable mapping.
        collectors = root / "src/seo_agent_suite/collectors"
        shutil.copytree(root / "scripts", collectors, dirs_exist_ok=True)
        (collectors / "__init__.py").write_text("")
        yield root


class AttemptCompatibilityTests(unittest.TestCase):
    def run_probe(self, root, script, collector_targets=TARGETS):
        # Prove both producer code and every collector used by the probe come
        # from the disposable tree. Hashes also prevent a false green against
        # an uncomposed classic collector when an editable install is present.
        source_hashes = {
            "seo_agent_suite." + name: hashlib.sha256(
                (ROOT / "src/seo_agent_suite" / (name + ".py")).read_bytes()).hexdigest()
            for name in ("cli", "mcp_server", "comparison_metadata", "comparison_runtime", "paths")
        }
        prelude = "\n".join([
            "import hashlib, sys",
            "from pathlib import Path",
            "root = Path(" + repr(str(root)) + ")",
            "sys.path.insert(0, str(root / 'src'))",
            "from seo_agent_suite import cli, mcp_server, comparison_metadata, comparison_runtime, paths",
            "site = paths.load_script('site_meta_audit.py')",
            "http = paths.load_script('public_http.py')",
            "for module in (cli, mcp_server, comparison_metadata, comparison_runtime, paths, site, http):",
            "    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__",
            "    if module.__name__ in " + repr(source_hashes) + ":",
            "        assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == " + repr(source_hashes) + "[module.__name__]",
            "for module, relative in ((site, 'scripts/site_meta_audit.py'), (http, 'scripts/public_http.py')):",
            "    assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == " + repr(collector_targets) + "[relative]",
            "",
        ])
        result = subprocess.run([sys.executable, "-c", prelude + script], cwd=root,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_exact_composed_cli_mcp_and_wheel_remain_known_complete(self):
        with composed_checkout() as root:
            self.run_probe(root, """
import runpy, unittest
ns = runpy.run_path('tests/test_comparison_metadata.py')
cls = ns['ComparisonContractTests']
suite = unittest.defaultTestLoader.loadTestsFromTestCase(cls)
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()
""")

    def test_exact_composed_variant_requires_actual_empty_context_and_none_defaults(self):
        with composed_checkout() as root:
            self.run_probe(root, """
import copy, inspect, runpy
from unittest.mock import patch
ns = runpy.run_path('tests/test_comparison_metadata.py')
from seo_agent_suite.comparison_runtime import resolve_site_runtime_policy as resolve
from seo_agent_suite.comparison_metadata import build_site_comparison_metadata as build
site = ns['cli'].load_script('site_meta_audit.py')
http = ns['cli'].load_script('public_http.py')
expected = ns['POLICY']
assert resolve(site, audit_options={}) == expected

def unknown(policy):
    report = ns['report_fixture']()
    block = build(report, ns['URL'], policy)
    assert block['scope']['configuration_status'] == 'unknown', policy
    assert block['collection']['completion'] == 'unknown', block
    assert 'configuration_unverified' in block['collection']['reasons']

unknown(resolve(site))  # Missing invocation context is not an empty invocation.
for context in (None, [], False, {'max_http_attempts': None},
                {'max_http_attempts': 0}, {'max_http_attempts': 10}, {'other': 1}):
    unknown(resolve(site, audit_options=context))
slots = [(site.audit, 'max_http_attempts'), (site.fetch, 'budget'),
         (site.fetch_public_url, 'budget'), (http.follow_public_http, 'budget'),
         (http.request_public_url_once, 'budget'), (http.request_via_proxy, 'budget')]
for function, parameter in slots:
    saved = function.__kwdefaults__
    try:
        for value in (0, False, http.HTTPAttemptBudget(1)):
            function.__kwdefaults__ = {**saved, parameter: value}
            unknown(resolve(site, audit_options={}))
        function.__kwdefaults__ = {k: v for k, v in saved.items() if k != parameter}
        # A missing bound default must not be confused with actual None.
        unknown(resolve(site, audit_options={}))
        advertised = inspect.signature(function).replace(parameters=[
            p.replace(default=None) if p.name == parameter else p
            for p in inspect.signature(function).parameters.values()])
        with patch.object(function, '__signature__', advertised, create=True):
            unknown(resolve(site, audit_options={}))
    finally:
        function.__kwdefaults__ = saved
    assert resolve(site, audit_options={}) == expected
# Current mutable constants do not replace the callable's actual binding.
with patch.object(http, 'DEFAULT_MAX_BODY_BYTES', 7):
    assert resolve(site, audit_options={})['max_body_bytes'] == 1000000
# An unknown wrapper with an identical-looking signature is still unknown.
def audit(url, *, max_http_attempts=None): return {}
with patch.object(site, 'audit', audit):
    unknown(resolve(site, audit_options={}))
""")


if __name__ == "__main__":
    unittest.main()
