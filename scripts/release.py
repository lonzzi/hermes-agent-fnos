#!/usr/bin/env python3
"""Resolve official stable release and published multi-platform image; build an FPK."""
import argparse, hashlib, json, os, pathlib, re, shutil, subprocess, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[1]
UPSTREAM = 'NousResearch/hermes-agent'
IMAGE = 'nousresearch/hermes-agent'

def api(path, missing=False):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'hermes-agent-fnos'}
    if os.getenv('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    try:
        with urllib.request.urlopen(urllib.request.Request('https://api.github.com/' + path, headers=headers), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if missing and e.code == 404:
            return None
        raise

def detect():
    requested = os.getenv('UPSTREAM_TAG', '')
    if requested and not re.fullmatch(r'v?\d+\.\d+\.\d+', requested):
        raise ValueError('Only numeric stable release tags are supported')
    release = api(f'repos/{UPSTREAM}/releases/' + ('tags/' + requested if requested else 'latest'))
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v?\d+\.\d+\.\d+', tag):
        raise ValueError('Unsupported or non-stable upstream release; review before packaging')
    revision = os.getenv('PACKAGE_REVISION', '1')
    if not re.fullmatch(r'[1-9]\d{0,3}', revision):
        raise ValueError('Invalid package revision')
    release_tag = f'{tag}-fnos.{revision}'
    existing = api(f"repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{release_tag}", missing=True)
    should_build = existing is None or existing['draft']
    values = {'build': str(should_build).lower(), 'tag': tag, 'release_tag': release_tag,
              'version': tag.lstrip('v') + '.' + revision}
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for key, value in values.items():
            f.write(f'{key}={value}\n')
    print(json.dumps(values))

def stable_release(tag):
    release = api(f'repos/{UPSTREAM}/releases/tags/{tag}')
    if release['tag_name'] != tag or release['draft'] or release['prerelease']:
        raise ValueError('Image resolution requires the requested published stable release')
    return release


def tag_record(tag_object):
    # Upstream signs some annotated tags; the signature follows the JSON record.
    message = tag_object.get('message', '').split('\n-----BEGIN ', 1)[0].strip()
    if not message.startswith(('{', '[')):
        # Legacy annotated tags contain ordinary release notes, not receipts.
        return None
    record = json.loads(message)
    if not isinstance(record, dict):
        raise ValueError('Invalid upstream release receipt')
    return record


def resolve_image(tag):
    """Bind a published release to its receipt digest, or its legacy image tag."""
    release = stable_release(tag)
    ref = api(f'repos/{UPSTREAM}/git/ref/tags/{tag}')
    obj = ref['object']
    provenance = {'upstream_tag_object': obj['sha']}
    pinned = None
    if obj['type'] == 'tag':
        annotated = api(f"repos/{UPSTREAM}/git/tags/{obj['sha']}")
        record = tag_record(annotated)
        if record is not None:
            commit = annotated['object']['sha']
            claim_tag = record.get('claimTag', '')
            claim_object = record.get('claimTagObject', '')
            digest = record.get('dockerManifestDigest', '')
            if (annotated.get('sha') != obj['sha'] or annotated.get('tag') != tag
                    or annotated['object']['type'] != 'commit'
                    or not re.fullmatch(r'[0-9a-f]{40}', commit)
                    or record.get('schema') != 1
                    or record.get('version') != tag.lstrip('v')
                    or record.get('commit') != commit
                    or record.get('releaseId') != release['id']
                    or not isinstance(claim_tag, str)
                    or not re.fullmatch(r'rc\.[1-9]\d*-v' + re.escape(tag.lstrip('v')), claim_tag)
                    or not isinstance(claim_object, str)
                    or not re.fullmatch(r'[0-9a-f]{40}', claim_object)
                    or not isinstance(digest, str)
                    or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
                raise ValueError('Upstream release receipt identity or Docker digest is invalid')
            claim = api(f'repos/{UPSTREAM}/git/tags/{claim_object}')
            claim_record = tag_record(claim)
            if (claim.get('sha') != claim_object or claim.get('tag') != claim_tag
                    or claim.get('object', {}).get('type') != 'commit'
                    or claim['object']['sha'] != commit or claim_record is None
                    or claim_record.get('schema') != 1
                    or claim_record.get('commit') != commit
                    or claim_record.get('version') != record['version']
                    or claim_record.get('attempt') != int(claim_tag.split('-')[0].split('.')[1])):
                raise ValueError('Upstream release claim differs from the final receipt')
            pinned = f'{IMAGE}@{digest}'
            provenance.update(image_resolution='release-receipt', upstream_commit=commit,
                              upstream_image_tag=claim_tag)
    elif obj['type'] != 'commit':
        raise ValueError('Unsupported upstream release tag object')
    if pinned is None:
        # Old releases predate receipts. Resolve their exact tag once; never use
        # moving stable/latest aliases or guess which release attempt succeeded.
        image_tag = f'{IMAGE}:{tag}'
        info = subprocess.check_output(['docker','buildx','imagetools','inspect',image_tag], text=True)
        match = re.search(r'^Digest:\s+(sha256:[0-9a-f]{64})\s*$', info, re.M)
        if not match:
            raise ValueError('Image index digest not found')
        pinned = f'{IMAGE}@{match[1]}'
        provenance.update(image_resolution='legacy-version-tag', upstream_image_tag=tag)
    index = json.loads(subprocess.check_output(['docker','buildx','imagetools','inspect','--raw',pinned], text=True))
    platforms = {(m.get('platform',{}).get('os'), m.get('platform',{}).get('architecture'))
                 for m in index.get('manifests', [])}
    if not {('linux','amd64'), ('linux','arm64')} <= platforms:
        raise ValueError('Upstream image must support linux/amd64 AND linux/arm64')
    return pinned, provenance


def build(tag, version, fnpack):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', tag) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version):
        raise ValueError('Invalid version')
    pinned, image_provenance = resolve_image(tag)
    stage = ROOT / '.build' / 'package'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name in ('app','cmd','config','wizard'):
        shutil.copytree(ROOT/name, stage/name, ignore=shutil.ignore_patterns('.DS_Store'))
    for name in ('manifest','ICON.PNG','ICON_256.PNG'):
        shutil.copy2(ROOT/name, stage/name)
    manifest = stage/'manifest'
    manifest.write_text(re.sub(r'^version=.*$', 'version='+version, manifest.read_text(), flags=re.M))
    compose = stage/'app/docker/docker-compose.yaml'
    compose.write_text(compose.read_text().replace('@@IMAGE@@', pinned))
    provenance = {'upstream_repository': UPSTREAM, 'upstream_tag': tag, 'package_version': version,
                  **image_provenance, 'image': pinned, 'platforms':['linux/amd64','linux/arm64'], 'fnpack':'1.2.3'}
    (stage/'app/upstream.json').write_text(json.dumps(provenance,indent=2)+'\n')
    subprocess.run([str(pathlib.Path(fnpack).resolve()),'build'],cwd=stage,check=True)
    artifacts = list(stage.glob('*.fpk'))
    if len(artifacts) != 1:
        raise ValueError('fnpack did not produce exactly one package')
    dist = ROOT/'dist'
    dist.mkdir(exist_ok=True)
    target = dist/f'hermes-agent-fnos-{version}-all.fpk'
    shutil.copy2(artifacts[0],target)
    (dist/'upstream.json').write_text(json.dumps(provenance,indent=2)+'\n')
    (dist/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in (target,dist/'upstream.json')))
    (dist/'release-notes.md').write_text(f"""Hermes Agent for fnOS — {version}

上游正式版本：[{tag}](https://github.com/{UPSTREAM}/releases/tag/{tag})

- 支持 x86_64 / ARM64；安装前启用飞牛 Docker。
- 下载 `.fpk`，在应用中心选择「手动安装」。
- 安装向导设置独立登录密码；控制台默认端口 19119。
- 安装及升级需要联网拉取官方 Docker 镜像；本包不含离线镜像。
- 升级保留应用运行数据；操作前请备份。卸载时不要删除需要保留的数据。
- 自动化检查不代表已经通过飞牛实机安装、升级验证。

镜像固定为 `{pinned}`。
校验文件：`SHA256SUMS`；构建来源：`upstream.json`。
""")
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            f.write('image='+pinned+'\n')
    print(target)

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('detect')
    b=sub.add_parser('build')
    b.add_argument('--tag',required=True)
    b.add_argument('--version',required=True)
    b.add_argument('--fnpack',required=True)
    args=parser.parse_args()
    if args.command == 'detect': detect()
    else: build(args.tag,args.version,args.fnpack)
