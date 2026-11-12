import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sources import TreeSource, package_dependencies  # noqa: E402


class PackageDependenciesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()
        self.data = Path(tmp.name) / "data"

    def dependencies(self, value):
        (self.root / "package.json").write_text(json.dumps(value), encoding="utf-8")
        return package_dependencies(TreeSource(self.root))

    def test_non_object_manifest_has_no_dependencies(self):
        for value in (None, [], ["sqlite3"], "sqlite3", 42, True):
            with self.subTest(value=value):
                self.assertEqual(self.dependencies(value), {"runtime": set(), "dev": set()})

    def test_non_object_field_does_not_hide_the_other_field(self):
        for invalid in (None, [], ["sqlite3"], [{"sqlite3": "1"}], "sqlite3", 42, True):
            for field, other, output, other_output in (
                ("dependencies", "devDependencies", "runtime", "dev"),
                ("devDependencies", "dependencies", "dev", "runtime"),
            ):
                with self.subTest(invalid=invalid, field=field):
                    result = self.dependencies({field: invalid, other: {"valid-package": "1"}})
                    self.assertEqual(result[output], set())
                    self.assertEqual(result[other_output], {"valid-package"})

    def test_object_fields_keep_package_names_not_versions(self):
        self.assertEqual(
            self.dependencies({"dependencies": {"sqlite3": "1", "@scope/pkg": "2"},
                               "devDependencies": {"test-tool": "3"}}),
            {"runtime": {"sqlite3", "@scope/pkg"}, "dev": {"test-tool"}},
        )

    def test_missing_fields_are_empty(self):
        self.assertEqual(self.dependencies({"name": "synthetic"}), {"runtime": set(), "dev": set()})

    def test_missing_or_invalid_json_remains_empty(self):
        self.assertEqual(package_dependencies(TreeSource(self.root)), {"runtime": set(), "dev": set()})
        (self.root / "package.json").write_text("{invalid", encoding="utf-8")
        self.assertEqual(package_dependencies(TreeSource(self.root)), {"runtime": set(), "dev": set()})

    def test_real_mcp_build_accepts_non_object_manifest_and_fields(self):
        for value in ([], None, "text", 42, True,
                      {"dependencies": 42, "devDependencies": [{"bad": "value"}]}):
            with self.subTest(value=value):
                self.dependencies_for_build(value)

    def dependencies_for_build(self, value):
        (self.root / "package.json").write_text(json.dumps(value), encoding="utf-8")
        (self.root / "schema.sql").write_text("CREATE TABLE notes (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
        (self.root / "index.ts").write_text('import { DatabaseSync } from "node:sqlite";\n', encoding="utf-8")
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "build", "arguments": {"repo_path": str(self.root)}}}
        done = subprocess.run(
            [sys.executable, str(ROOT / "mcp_server" / "server.py")],
            input=json.dumps(request) + "\n", capture_output=True, text=True, timeout=20,
            env={**os.environ, "SYSTEM_MAP_DATA": str(self.data), "PYTHONDONTWRITEBYTECODE": "1"},
            check=True,
        )
        reply = json.loads(done.stdout)
        self.assertNotIn("error", reply, reply)
        self.assertFalse(reply["result"].get("isError", False), reply)


if __name__ == "__main__":
    unittest.main()
