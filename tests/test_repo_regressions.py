#!/usr/bin/env python3
"""Offline regressions for repository evidence and explicit public registries."""
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repo_regressions', ROOT / 'scripts/repo_seo_baseline.py')
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class RepoRegressions(unittest.TestCase):
    def run_main(self, root, *options, command=None):
        def default_command(args, **kwargs):
            if args[:3] == ['gh', 'repo', 'view']:
                return {'status': 'ok', 'stdout': json.dumps({'homepageUrl': 'https://site.example/?lang=zh'})}
            return {'status': 'ok', 'stdout': ''}
        stream = io.StringIO()
        with mock.patch.object(sys, 'argv', ['repo', '--root', str(root), '--json', *options]), mock.patch.object(repo, 'run_cmd', side_effect=command or default_command) as run, mock.patch.object(repo.public_http, 'fetch_public_url', return_value={'status': 'ok', 'body': '{"crate": {"id": "demo", "max_version": "1.0.0"}}', 'body_truncated': False}), mock.patch.object(repo, 'site_resource_checks', return_value={'homepage': {'status': 'ok'}}) as site, redirect_stdout(stream):
            code = repo.main()
        return code, json.loads(stream.getvalue()), run, site

    def test_homepage_query_preserved(self):
        self.assertEqual(repo.normalize_homepage('https://site.example/docs/?lang=zh#part'), 'https://site.example/docs/?lang=zh')

    def test_homepage_path_slashes_remain_distinct(self):
        urls = ['https://site.example/docs', 'https://site.example/docs/',
                'https://site.example/docs//', 'https://site.example/docs/;v=1?lang=zh']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(repo.normalize_homepage(url + '#part'), url)
        manifests = {'npm': [{'homepage': url} for url in urls], 'errors': []}
        self.assertEqual(repo.infer_homepages(manifests), urls)

    def test_explicit_homepage_keeps_directory_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, site = self.run_main(Path(tmp), '--homepage', 'https://site.example/docs/')
        self.assertIn(mock.call('https://site.example/docs/'), site.call_args_list)

    def test_nonfinite_json_numbers_are_structured_manifest_errors(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e9999'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package.json').write_text('{"publishConfig": {"number": ' + value + '}}')
                code, payload, _, _ = self.run_main(root)
                self.assertEqual(code, 1)
                self.assertEqual(payload['manifests']['npm'], [])
                self.assertEqual(payload['manifests']['errors'][0]['status'], 'error')
                json.dumps(payload, allow_nan=False)

    def test_finite_manifest_numbers_keep_their_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'package.json'
            path.write_text('{"integer":9007199254740993,"decimal":1.25,"exponent":1e3}')
            data, diagnostic = repo.read_json(path)
        self.assertIsNone(diagnostic)
        self.assertEqual(data, {'integer': 9007199254740993, 'decimal': 1.25, 'exponent': 1000.0})

    def test_json_decoder_limits_become_structured_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'package.json'
            path.write_text('{}')
            for error in (ValueError('integer conversion limit'), RecursionError('nesting')):
                with self.subTest(error=type(error).__name__), mock.patch.object(repo.json, 'loads', side_effect=error):
                    data, diagnostic = repo.read_json(path)
                self.assertIsNone(data)
                self.assertEqual(diagnostic['status'], 'error')
                self.assertIn('JSON', diagnostic['reason'])

    def test_invalid_homepages_do_not_abort_metadata(self):
        for value in ([], 42, {}, 'https://[bad/', 'https://site.example:bad/', 'https:///missing', 'ftp://site.example'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package.json').write_text(json.dumps({'homepage': value, 'description': 'kept'}))
                code, payload, _, _ = self.run_main(root)
                self.assertEqual(code, 1)
                self.assertEqual(payload['manifests']['npm'][0]['description'], 'kept')
                self.assertTrue(payload['manifests']['errors'])

    def test_urls_redacted_from_all_repository_evidence(self):
        secret = 'fake-secret'
        url = f'https://user:{secret}@site.example/repo'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({'repository': {'type': 'git', 'url': url}, 'homepage': url}))
            (root / 'pyproject.toml').write_text(f'[project.urls]\nRepository = "{url}"\n')
            def command(args, **kwargs):
                if args[:3] == ['git', 'remote', 'get-url']:
                    return {'status': 'ok', 'stdout': url, 'stderr': f'failed for {url}'}
                return {'status': 'ok', 'stdout': ''}
            _, payload, _, _ = self.run_main(root, command=command)
        self.assertNotIn(secret, json.dumps(payload))
        self.assertEqual(payload['manifests']['npm'][0]['repository']['url'], 'https://site.example/repo')

    def test_shipwise_unsupported_line_does_not_expose_scalar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'project.yaml'
            path.write_text('discoverability:\n invalid fake-secret\n')
            with self.assertRaises(ValueError) as caught:
                repo.parse_shipwise_discoverability(path)
        self.assertNotIn('fake-secret', str(caught.exception))

    def test_github_homepage_and_snapshot_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, payload, _, site = self.run_main(Path(tmp))
        site.assert_called_once_with('https://site.example?lang=zh')
        self.assertRegex(payload['collected_at'], r'Z$')
        self.assertIn('head', payload['git'])

    def test_private_npm_not_queried_unless_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({'name': 'private-demo', 'private': True}))
            _, payload, run, _ = self.run_main(root)
            self.assertEqual(payload['registry']['npm'], {})
            self.assertFalse(any(call.args[0][0] == 'npm' for call in run.call_args_list))
            _, payload, run, _ = self.run_main(root, '--npm', 'private-demo')
            args = next(call.args[0] for call in run.call_args_list if call.args[0][0] == 'npm')
            self.assertIn('https://registry.npmjs.org', args)
            self.assertIn('private-demo', payload['registry']['npm'])

    def test_github_supported_community_locations_and_real_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs').mkdir()
            (root / '.github/ISSUE_TEMPLATE').mkdir(parents=True)
            for filename in ('README.md', 'CONTRIBUTING.md', 'CODE_OF_CONDUCT.md', 'SECURITY.md'):
                (root / 'docs' / filename).write_text('# content')
            (root / '.github/ISSUE_TEMPLATE/notes.txt').write_text('not a template')
            files = repo.collect_community_files(root)
            self.assertTrue(all(files[key] for key in ('readme', 'contributing', 'code_of_conduct', 'security')))
            self.assertFalse(files['issue_templates'])
            (root / '.github/ISSUE_TEMPLATE/bug.yml').write_text('name: Bug\nbody:\n  - type: textarea\n    id: problem\n    attributes:\n      label: Problem\n')
            self.assertTrue(repo.collect_community_files(root)['issue_templates'])
            self.assertEqual(repo.collect_readmes(root)[0]['path'], 'docs/README.md')

    def test_workspace_metadata_only_includes_actual_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text('[workspace]\nmembers = ["crates/*"]\n[workspace.package]\nhomepage = "https://site.example"\n')
            data = {'workspace_members': ['member-id'], 'packages': [
                {'id': 'member-id', 'name': 'member', 'version': '1.2.3', 'homepage': 'https://site.example', 'manifest_path': str(root / 'crates/member/Cargo.toml')},
                {'id': 'dep-id', 'name': 'dependency', 'manifest_path': '/other/Cargo.toml'}]}
            with mock.patch.object(repo, 'run_cmd', return_value={'status': 'ok', 'stdout': json.dumps(data)}) as run:
                manifests = repo.collect_manifests(root)
            self.assertEqual([item['name'] for item in manifests['cargo_members']], ['member'])
            self.assertEqual(manifests['cargo_members'][0]['version'], '1.2.3')
            self.assertIn('--no-deps', run.call_args.args[0])

    def test_crate_exact_match_and_local_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text('[package]\nname = "demo"\nversion = "2.0.0"\n')
            def command(args, **kwargs):
                return {'status': 'ok', 'stdout': 'demo-other = "9.0.0" # unrelated\ndemo = "1.0.0" # right'}
            _, payload, _, _ = self.run_main(root, command=command)
            item = payload['registry']['crates']['demo']
            self.assertEqual(item['published_version'], '1.0.0')
            self.assertEqual(item['local_version'], '2.0.0')
            self.assertFalse(item['version_matches'])
            with mock.patch.object(repo.public_http, 'fetch_public_url', return_value={'status': 'ok', 'body': '{"crate": {"id": "demo-other", "max_version": "1.0.0"}}'}):
                self.assertEqual(repo.crate_registry_check('demo')['status'], 'error')

    def test_workspace_without_members_resolves_root_inheritance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text(
                '[package]\nname = "root-demo"\nversion.workspace = true\n'
                'homepage.workspace = true\n[workspace]\n'
                '[workspace.package]\nversion = "2.1.0"\nhomepage = "https://site.example"\n')
            data = {'workspace_members': ['root-id'], 'packages': [{
                'id': 'root-id', 'name': 'root-demo', 'version': '2.1.0',
                'homepage': 'https://site.example', 'manifest_path': str(root / 'Cargo.toml')} ]}
            with mock.patch.object(repo, 'run_cmd', return_value={'status': 'ok', 'stdout': json.dumps(data)}):
                manifests = repo.collect_manifests(root)
            self.assertEqual(manifests['cargo']['version'], '2.1.0')
            self.assertEqual(manifests['cargo']['homepage'], 'https://site.example')
            self.assertEqual(manifests['errors'], [])

    def test_empty_workspace_members_still_collects_implicit_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text(
                '[package]\nname = "root-demo"\nversion = "1.0.0"\n'
                '[workspace]\nmembers = []\n')
            data = {'workspace_members': ['root-id', 'implicit-id'], 'packages': [
                {'id': 'root-id', 'name': 'root-demo', 'version': '1.0.0',
                 'manifest_path': str(root / 'Cargo.toml')},
                {'id': 'implicit-id', 'name': 'implicit-demo', 'version': '1.2.0',
                 'manifest_path': str(root / 'implicit/Cargo.toml')},
                {'id': 'excluded-id', 'name': 'excluded-demo', 'version': '1.0.0',
                 'manifest_path': '/excluded/Cargo.toml'}]}
            with mock.patch.object(repo, 'run_cmd', return_value={'status': 'ok', 'stdout': json.dumps(data)}):
                manifests = repo.collect_manifests(root)
            self.assertEqual([item['name'] for item in manifests['cargo_members']], ['implicit-demo'])

    def test_crate_api_only_asserts_missing_on_404(self):
        cases = [
            ({'status': 'error', 'http_status': 404}, 'missing'),
            ({'status': 'error', 'http_status': 429}, None),
            ({'status': 'ok', 'body': 'not json'}, None),
            ({'status': 'ok', 'body': '{"crate": {"id": "demo", "max_version": "1.0.0"}}', 'body_truncated': True}, None),
        ]
        for response, observation in cases:
            with self.subTest(response=response), mock.patch.object(repo.public_http, 'fetch_public_url', return_value=response) as fetch:
                result = repo.crate_registry_check('demo', '1.0.0')
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result.get('observation'), observation)
                fetch.assert_called_once_with('https://crates.io/api/v1/crates/demo')
                self.assertNotIn('body', result)

    def test_workspace_failure_is_structured_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text('[workspace]\nmembers = ["member"]\n')
            with mock.patch.object(repo, 'run_cmd', return_value={'status': 'error', 'stdout': 'https://user:fake-secret@site.example'}) as run:
                manifests = repo.collect_manifests(root)
            self.assertEqual(manifests['errors'][0]['status'], 'error')
            self.assertIn('--locked', run.call_args.args[0])
            self.assertIn('--offline', run.call_args.args[0])
            self.assertNotIn('fake-secret', json.dumps(manifests))

    def test_resource_results_are_json_serializable_and_preserve_failures(self):
        robots = {'status': 'error', 'present': False, 'http_status': 404, 'observation': 'not_configured'}
        sitemap = {'status': 'ok', 'present': False, 'reason': 'not XML'}
        with mock.patch.object(repo, 'http_check', return_value={'status': 'ok'}), mock.patch.object(repo, 'crawl_resource_checks', return_value={'robots_txt': [robots], 'sitemap_xml': [sitemap]}):
            checks = repo.site_resource_checks('https://site.example')
        json.dumps(checks)
        self.assertEqual(checks['sitemap']['status'], 'error')
        errors = repo.collect_errors({'site': {'https://site.example': checks}})
        self.assertEqual([error['resource'] for error in errors], ['sitemap'])
        self.assertEqual(sitemap['status'], 'ok')

    def test_private_npm_retains_public_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text('{"name": "private-demo", "private": true}')
            (root / 'packages/public').mkdir(parents=True)
            (root / 'packages/public/package.json').write_text('{"name": "public-demo"}')
            _, payload, _, _ = self.run_main(root)
            self.assertEqual(set(payload['registry']['npm']), {'public-demo'})

    def test_multiple_manifest_shapes_redact_url_credentials(self):
        url = 'git+https://user:fake-secret@site.example/source'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({'repository': url, 'publishConfig': {'registry': url}}))
            (root / 'Cargo.toml').write_text(f'[package]\nrepository = "{url}"\n')
            _, payload, _, _ = self.run_main(root)
        self.assertNotIn('fake-secret', json.dumps(payload))
        self.assertEqual(payload['manifests']['cargo']['repository'], 'git+https://site.example/source')

    def test_git_metadata_homepage_deduplicates_manifest_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text('{"homepage": "https://site.example?lang=zh"}')
            _, _, _, site = self.run_main(root, '--homepage', 'https://site.example?lang=zh')
        site.assert_called_once_with('https://site.example?lang=zh')

    def test_crate_auto_queries_only_public_publish_targets(self):
        cases = [('false', False), ('["internal"]', False), ('[]', False), ('["crates-io"]', True), ('true', True), (None, True)]
        for publish, expected in cases:
            with self.subTest(publish=publish), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = '[package]\nname = "demo"\nversion = "1.0.0"\n'
                if publish is not None:
                    manifest += f'publish = {publish}\n'
                (root / 'Cargo.toml').write_text(manifest)
                with mock.patch.object(repo, 'crate_registry_check', return_value={'status': 'ok'}) as check:
                    _, payload, _, _ = self.run_main(root)
                    self.assertEqual(bool(check.call_count), expected)
                    self.assertEqual(bool(payload['registry']['crates']), expected)
                with mock.patch.object(repo, 'crate_registry_check', return_value={'status': 'ok'}) as check:
                    self.run_main(root, '--crate', 'demo')
                    check.assert_called_once_with('demo', '1.0.0', None)

    def test_community_path_evidence_reports_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs').mkdir()
            (root / 'docs/CONTRIBUTING.md').write_text('# Contributions')
            (root / '.github/ISSUE_TEMPLATE').mkdir(parents=True)
            (root / '.github/ISSUE_TEMPLATE/bug.md').write_text('# Bug')
            (root / '.github/ISSUE_TEMPLATE/config.yml').write_text('blank_issues_enabled: false')
            files = repo.collect_community_files(root)
            self.assertEqual(files['community_file_paths']['contributing'], ['docs/CONTRIBUTING.md'])
            self.assertEqual(files['issue_template_candidates'], ['.github/ISSUE_TEMPLATE/bug.md'])
            project = root / 'project.yaml'
            project.write_text('discoverability:\n  description: demo tool\n  primary_keyword: demo\n')
            result = repo.evaluate_shipwise_project(root, project)
            evidence = result['checks']['support_path']['evidence']
            self.assertEqual(evidence['validation_scope'], 'candidate file presence; GitHub support path not validated')

    def test_sitemap_discovery_scope_is_preserved_without_fabrication(self):
        scope = {'declared_count': 8, 'candidate_count': 10, 'checked_count': 4, 'omitted_count': 6, 'complete': False}
        candidates = {'robots_txt': [{'status': 'ok', 'present': True}], 'sitemap_xml': [{'status': 'ok', 'present': True}]}
        with mock.patch.object(repo, 'http_check', return_value={'status': 'ok'}), mock.patch.object(repo, 'crawl_resource_checks', return_value={**candidates, 'sitemap_discovery': scope}):
            checks = repo.site_resource_checks('https://site.example')
            self.assertEqual(checks['sitemap']['sitemap_discovery'], scope)
        with mock.patch.object(repo, 'http_check', return_value={'status': 'ok'}), mock.patch.object(repo, 'crawl_resource_checks', return_value=candidates):
            checks = repo.site_resource_checks('https://site.example')
            self.assertNotIn('sitemap_discovery', checks['sitemap'])

    def test_same_name_registry_packages_require_repository_relationship(self):
        expected = 'https://github.com/fixture/current'
        for repository, matches in [('https://github.com/fixture/other', False),
                                    ('git+https://github.com/fixture/current.git', True),
                                    (None, None)]:
            with self.subTest(repository=repository):
                crate = {'id': 'demo', 'max_version': '1.0.0', 'repository': repository}
                npm = {'name': 'demo', 'version': '1.0.0', 'repository': {'url': repository}}
                with mock.patch.object(repo.public_http, 'fetch_public_url', return_value={
                        'status': 'ok', 'body': json.dumps({'crate': crate})}):
                    result = repo.crate_registry_check('demo', '1.0.0', expected)
                self.assertIs(result['repository_matches'], matches)
                with mock.patch.object(repo, 'run_cmd', return_value={
                        'status': 'ok', 'stdout': json.dumps(npm)}):
                    result = repo.npm_registry_check('demo', '1.0.0', expected)
                self.assertIs(result['repository_matches'], matches)

    def test_npm_wrong_name_and_invalid_response_stay_unverified(self):
        for body in ('{}', '[]', 'not json', '{"name":"other","version":"1.0.0"}'):
            with self.subTest(body=body), mock.patch.object(repo, 'run_cmd', return_value={
                    'status': 'ok', 'stdout': body}):
                result = repo.npm_registry_check('demo')
            self.assertEqual(result['status'], 'error')
            self.assertNotIn('published_version', result)

    def test_npm_metadata_redaction_handles_json_escaped_url_credentials(self):
        for name in ('demo', 'other'):
            body = json.dumps({'name': name, 'version': '1.0.0',
                               'repository': 'https://user:fake-secret@github.com/fixture/current'}).replace('/', r'\u002f')
            with self.subTest(name=name), mock.patch.object(repo, 'run_cmd', return_value={
                    'status': 'ok', 'stdout': body}):
                result = repo.redact_evidence(repo.npm_registry_check('demo'))
            self.assertNotIn('fake-secret', json.dumps(result))
            self.assertNotIn('stdout', result)

    def test_repository_links_compare_transport_without_guessing_other_paths(self):
        expected = repo.repository_identity('https://github.com/Fixture/Current')
        for value in ('git@github.com:fixture/current.git', 'ssh://git@github.com/fixture/current.git',
                      'github:fixture/current', 'fixture/current', {'url': 'git+https://github.com/fixture/current.git'}):
            with self.subTest(value=value):
                self.assertEqual(repo.repository_identity(value), expected)
        self.assertNotEqual(repo.repository_identity('https://example.com/Fixture/Current'),
                            repo.repository_identity('https://example.com/fixture/current'))
        self.assertIsNone(repo.repository_identity('https://github.com/fixture/current/tree/main'))
        self.assertIsNone(repo.repository_identity('https://github.com/fixture/current?different=1'))

    def test_alternative_npm_registry_is_not_automatically_a_publication_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({
                'name': 'demo', 'publishConfig': {'registry': 'https://registry.example/internal'}}))
            _, payload, run, _ = self.run_main(root)
            self.assertEqual(payload['registry']['npm'], {})
            self.assertFalse(any(call.args[0][0] == 'npm' for call in run.call_args_list))

    def test_optional_metadata_does_not_block_source_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# Fixture\nUse the source; support: https://example.com/help')
            (root / 'LICENSE').write_text('MIT')
            project = root / 'project.yaml'
            project.write_text('discoverability:\n  description: A source collection\n'
                               '  primary_keyword: useful references\n  topics:\n    - references\n'
                               '  social_image_set: false\n')
            code, payload, _, _ = self.run_main(root, '--project-yaml', str(project))
            self.assertEqual(code, 0)
            self.assertEqual(payload['errors'], [])
            self.assertEqual(payload['shipwise']['checks']['topics_count']['status'], 'ok')
            self.assertTrue(any(f['id'] == 'repo.shipwise.social_image_set' and
                                f['status'] == 'unknown' and f['severity'] == 'low'
                                for f in payload['findings']))
            self.assertTrue(all(f['status'] != 'fail' for f in payload['findings']))

    def test_registry_relationship_is_visible_in_findings_from_current_repo_identity(self):
        for declared, matches in [('https://github.com/fixture/other', False), (None, None),
                                  ('https://github.com/fixture/current.git', True)]:
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package.json').write_text('{"name":"demo","version":"1.0.0"}')
                def command(args, **kwargs):
                    if args[:3] == ['gh', 'repo', 'view']:
                        return {'status': 'ok', 'stdout': '{"nameWithOwner":"fixture/current"}'}
                    if args[0] == 'npm':
                        return {'status': 'ok', 'stdout': json.dumps({
                            'name': 'demo', 'version': '1.0.0', 'repository': declared})}
                    return {'status': 'skipped'}
                code, payload, _, _ = self.run_main(root, command=command)
                self.assertEqual(code, 0)
                self.assertIs(payload['registry']['npm']['demo']['repository_matches'], matches)
                finding = next(f for f in payload['findings'] if f['id'] == 'repo.registry.npm.demo')
                self.assertEqual(finding['status'], 'pass' if matches else 'unknown')
                self.assertNotEqual(finding['status'], 'fail')

    def test_support_doc_alone_is_a_candidate_and_never_proof_of_usability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# Fixture')
            (root / 'LICENSE').write_text('MIT')
            (root / 'SUPPORT.md').write_text('Contact the maintainers via the documented route.')
            project = root / 'project.yaml'
            project.write_text('discoverability:\n  description: Fixture\n')
            code, payload, _, _ = self.run_main(root, '--project-yaml', str(project))
            self.assertEqual(code, 0)
            self.assertEqual(payload['shipwise']['checks']['support_path']['status'], 'ok')
            finding = next(f for f in payload['findings'] if f['id'] == 'repo.shipwise.support_path')
            self.assertEqual(finding['status'], 'unknown')

    def test_topic_maximum_still_fails_but_small_topic_sets_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# Fixture')
            (root / 'LICENSE').write_text('MIT')
            project = root / 'project.yaml'
            for count in (0, 1, 4, 20, 21):
                project.write_text('discoverability:\n  topics:\n' +
                                   ''.join(f'    - topic-{i}\n' for i in range(count)))
                code, payload, _, _ = self.run_main(root, '--project-yaml', str(project))
                self.assertEqual(code, 1 if count > 20 else 0)
                self.assertEqual(bool(payload['errors']), count > 20)

    @unittest.skipUnless(shutil.which('cargo'), 'Cargo is needed for real workspace collection')
    def test_real_virtual_workspace_inheritance_without_lockfile_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'Cargo.toml').write_text('[workspace]\nmembers = ["crates/*"]\n'
                                           'exclude = ["crates/excluded"]\nresolver = "2"\n'
                                           '[workspace.package]\nversion = "1.2.3"\n'
                                           'homepage = "https://site.example/project"\n'
                                           'repository = "https://github.com/fixture/current"\n')
            for name in ('member', 'excluded'):
                path = root / 'crates' / name
                (path / 'src').mkdir(parents=True)
                (path / 'src/lib.rs').write_text('')
                (path / 'Cargo.toml').write_text('[package]\nname = "' + name + '"\n'
                                               'version.workspace = true\nhomepage.workspace = true\n'
                                               'repository.workspace = true\n')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            manifests = repo.collect_manifests(root)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(manifests['errors'], [])
            self.assertEqual([p['name'] for p in manifests['cargo_members']], ['member'])
            self.assertEqual(manifests['cargo_members'][0]['version'], '1.2.3')
            self.assertEqual(manifests['cargo_members'][0]['homepage'], 'https://site.example/project')
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
