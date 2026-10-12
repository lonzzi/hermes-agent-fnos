#!/usr/bin/env python3
"""Offline regression tests for official release receipt image resolution."""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import release

TAG = 'v0.21.7'
COMMIT = 'a' * 40
TAG_OBJECT = 'b' * 40
CLAIM_OBJECT = 'c' * 40
DIGEST = 'sha256:' + 'd' * 64
PINNED = release.IMAGE + '@' + DIGEST


def fixtures():
    receipt = {'schema': 1, 'version': '0.21.7', 'commit': COMMIT,
               'claimTag': 'rc.15-v0.21.7', 'claimTagObject': CLAIM_OBJECT,
               'releaseId': 123, 'dockerManifestDigest': DIGEST}
    claim = {'schema': 1, 'version': '0.21.7', 'commit': COMMIT, 'attempt': 15}
    return [
        {'tag_name': TAG, 'draft': False, 'prerelease': False, 'id': 123},
        {'object': {'type': 'tag', 'sha': TAG_OBJECT}},
        {'sha': TAG_OBJECT, 'tag': TAG, 'object': {'type': 'commit', 'sha': COMMIT},
         'message': json.dumps(receipt)},
        {'sha': CLAIM_OBJECT, 'tag': 'rc.15-v0.21.7',
         'object': {'type': 'commit', 'sha': COMMIT}, 'message': json.dumps(claim)},
    ]


def index(arches=('amd64', 'arm64')):
    return json.dumps({'manifests': [{'platform': {'os': 'linux', 'architecture': arch}}
                                     for arch in arches]})


class ImageResolutionTests(unittest.TestCase):
    def resolve(self, responses=None, output=None):
        with patch.object(release, 'api', side_effect=responses or fixtures()) as api, \
                patch.object(release.subprocess, 'check_output', return_value=output or index()) as docker:
            result = release.resolve_image(TAG)
        return result, api, docker

    def test_receipt_pins_digest_without_inspecting_any_mutable_tag(self):
        (pinned, provenance), api, docker = self.resolve()
        self.assertEqual(pinned, PINNED)
        self.assertEqual(provenance['upstream_image_tag'], 'rc.15-v0.21.7')
        self.assertEqual(provenance['image_resolution'], 'release-receipt')
        self.assertEqual(provenance['upstream_commit'], COMMIT)
        self.assertEqual(api.call_args_list[-1].args[0],
                         f'repos/{release.UPSTREAM}/git/tags/{CLAIM_OBJECT}')
        docker.assert_called_once_with(
            ['docker', 'buildx', 'imagetools', 'inspect', '--raw', PINNED], text=True)

    def test_signed_receipt(self):
        responses = fixtures()
        responses[2]['message'] += '\n-----BEGIN PGP SIGNATURE-----\nexample'
        self.resolve(responses)

    def test_receipt_identity_mismatches_fail_without_fallback(self):
        for key, value in [('schema', 2), ('version', '0.21.8'), ('commit', 'e' * 40),
                           ('releaseId', 124), ('claimTag', 'rc.15-v0.21.8'),
                           ('claimTag', None), ('claimTagObject', 'bad'),
                           ('dockerManifestDigest', ''), ('dockerManifestDigest', None)]:
            with self.subTest(key=key, value=value):
                responses = fixtures()
                receipt = json.loads(responses[2]['message'])
                receipt[key] = value
                responses[2]['message'] = json.dumps(receipt)
                with patch.object(release, 'api', side_effect=responses), \
                        patch.object(release.subprocess, 'check_output') as docker:
                    with self.assertRaises(ValueError):
                        release.resolve_image(TAG)
                    docker.assert_not_called()

    def test_malformed_or_incomplete_receipt_fails_closed(self):
        for message in ['{broken', '{}', '[]']:
            responses = fixtures()
            responses[2]['message'] = message
            with self.subTest(message=message), self.assertRaises(ValueError):
                self.resolve(responses)

    def test_claim_mismatch_fails(self):
        for key, value in [('commit', 'f' * 40), ('attempt', 14), ('version', '0.21.6')]:
            responses = fixtures()
            record = json.loads(responses[3]['message'])
            record[key] = value
            responses[3]['message'] = json.dumps(record)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve(responses)

    def test_unpublished_or_different_release_rejected(self):
        for key, value in [('draft', True), ('prerelease', True), ('tag_name', 'v0.21.8')]:
            responses = fixtures()
            responses[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve(responses)

    def test_legacy_lightweight_and_annotated_tags(self):
        for annotated in (False, True):
            responses = fixtures()[:3 if annotated else 2]
            if annotated:
                responses[2]['message'] = 'Old stable release notes'
            else:
                responses[1]['object']['type'] = 'commit'
            with self.subTest(annotated=annotated), \
                    patch.object(release, 'api', side_effect=responses), \
                    patch.object(release.subprocess, 'check_output',
                                 side_effect=['Digest: ' + DIGEST + '\n', index()]) as docker:
                pinned, provenance = release.resolve_image(TAG)
                self.assertEqual(pinned, PINNED)
                self.assertEqual(provenance['image_resolution'], 'legacy-version-tag')
                self.assertEqual(docker.call_args_list[0].args[0][-1], release.IMAGE + ':' + TAG)
                self.assertEqual(docker.call_args_list[1].args[0][-1], PINNED)

    def test_missing_architecture_or_non_index_fails(self):
        for output in [index(('amd64',)), index(('arm64',)), '{}', index(('unknown',))]:
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.resolve(output=output)

    def test_registry_error_is_not_hidden(self):
        with patch.object(release, 'api', side_effect=fixtures()), \
                patch.object(release.subprocess, 'check_output',
                             side_effect=subprocess.CalledProcessError(1, 'docker')):
            with self.assertRaises(subprocess.CalledProcessError):
                release.resolve_image(TAG)

    def test_api_error_is_not_hidden(self):
        with patch.object(release, 'api', side_effect=RuntimeError('API unavailable')), \
                patch.object(release.subprocess, 'check_output') as docker:
            with self.assertRaises(RuntimeError):
                release.resolve_image(TAG)
            docker.assert_not_called()

    def test_build_persists_pinned_image_and_provenance(self):
        source_root = release.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            import shutil
            for name in ('app', 'cmd', 'config', 'wizard'):
                shutil.copytree(source_root / name, root / name)
            for name in ('manifest', 'ICON.PNG', 'ICON_256.PNG'):
                shutil.copy2(source_root / name, root / name)
            def fnpack(*args, **kwargs):
                (kwargs['cwd'] / 'test.fpk').write_bytes(b'test package')
            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'api', side_effect=fixtures()), \
                    patch.object(release.subprocess, 'check_output', return_value=index()), \
                    patch.object(release.subprocess, 'run', side_effect=fnpack), \
                    patch.dict(release.os.environ, {'GITHUB_OUTPUT': str(root / 'output')}):
                release.build(TAG, '0.21.7.1', '/fake/fnpack')
            compose = (root / '.build/package/app/docker/docker-compose.yaml').read_text()
            self.assertIn(PINNED, compose)
            self.assertNotIn('@@IMAGE@@', compose)
            provenance = json.loads((root / 'dist/upstream.json').read_text())
            self.assertEqual(provenance['image'], PINNED)
            self.assertEqual(provenance['upstream_image_tag'], 'rc.15-v0.21.7')
            self.assertIn('image=' + PINNED, (root / 'output').read_text())
            self.assertEqual((root / '.build/package/app/upstream.json').read_bytes(),
                             (root / 'dist/upstream.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
