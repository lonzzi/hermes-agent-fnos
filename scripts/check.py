#!/usr/bin/env python3
"""Portable checks for package structure, credentials and release selection."""
import importlib.util, json, os, pathlib, subprocess, tempfile
from unittest.mock import patch
root=pathlib.Path(__file__).resolve().parents[1]
for name in ['config/resource','config/privilege','app/ui/config','wizard/install']:
    json.loads((root/name).read_text())
for script in (root/'cmd').iterdir():
    if script.name.startswith('.'): continue
    subprocess.run(['bash','-n',str(script)],check=True)
with tempfile.TemporaryDirectory() as tmp:
    base=pathlib.Path(tmp)
    env={**os.environ,'TRIM_PKGETC':str(base/'etc'),'TRIM_PKGVAR':str(base/'var'),
         'TRIM_TEMP_LOGFILE':str(base/'error'),'wizard_username':'admin','wizard_password':'Test-password123!'}
    subprocess.run(['bash',str(root/'cmd/install_init')],env=env,check=True)
    config=base/'etc/dashboard.env'
    before=config.read_bytes()
    subprocess.run(['bash',str(root/'cmd/install_callback')],env=env,check=True)
    assert b'Test-password123!' in before
    assert b'HERMES_DASHBOARD_BASIC_AUTH_SECRET=' in before
    assert b'HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS=31536000' in before
    assert config.stat().st_mode & 0o777 == 0o600
    subprocess.run(['bash',str(root/'cmd/install_init')],env={**env,'wizard_username':'replacement','wizard_password':'Replacement123!'},check=True)
    assert config.read_bytes()==before
    for invalid in ['short','contains\nnewline123', '$(touch attacked)']:
        subprocess.run(['bash',str(root/'cmd/install_init')],env={**env,'wizard_password':invalid},check=True)
        assert config.read_bytes()==before
        invalid_base=base/('invalid-'+str(len(invalid)))
        invalid_env={**env,'TRIM_PKGETC':str(invalid_base/'etc'),'TRIM_PKGVAR':str(invalid_base/'var'),
                     'TRIM_TEMP_LOGFILE':str(invalid_base/'error'),'wizard_password':invalid}
        result=subprocess.run(['bash',str(root/'cmd/install_init')],env=invalid_env)
        assert result.returncode != 0
        assert not (invalid_base/'etc/dashboard.env').exists()
    (base/'var/hermes/sentinel').write_text('retained')
    subprocess.run(['bash',str(root/'cmd/upgrade_init')],env=env,check=True)
    subprocess.run(['bash',str(root/'cmd/upgrade_callback')],env=env,check=True)
    assert config.read_bytes()==before
    assert (base/'var/hermes/sentinel').read_text()=='retained'
    legacy=base/'legacy'
    (legacy/'etc').mkdir(parents=True)
    (legacy/'var/hermes').mkdir(parents=True)
    legacy_config=legacy/'etc/dashboard.env'
    legacy_config.write_text('HERMES_DASHBOARD_BASIC_AUTH_USERNAME=existing\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=Existing-password123!\n')
    legacy_env={**env,'TRIM_PKGETC':str(legacy/'etc'),'TRIM_PKGVAR':str(legacy/'var')}
    subprocess.run(['bash',str(root/'cmd/upgrade_init')],env=legacy_env,check=True)
    migrated=legacy_config.read_bytes()
    assert b'HERMES_DASHBOARD_BASIC_AUTH_USERNAME=existing' in migrated
    assert b'HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=Existing-password123!' in migrated
    assert b'HERMES_DASHBOARD_BASIC_AUTH_SECRET=' in migrated
    assert b'HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS=31536000' in migrated
    subprocess.run(['bash',str(root/'cmd/upgrade_init')],env=legacy_env,check=True)
    assert legacy_config.read_bytes()==migrated
    spec=importlib.util.spec_from_file_location('release',root/'scripts/release.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    release={'tag_name':'v2026.9.14','draft':False,'prerelease':False}
    for existing,expected in [(None,'true'),({'draft':False},'false'),({'draft':True},'true')]:
        out=base/'output'; out.write_text('')
        with patch.dict(os.environ,{'GITHUB_OUTPUT':str(out),'GITHUB_REPOSITORY':'owner/repo','UPSTREAM_TAG':'','PACKAGE_REVISION':'1'}), patch.object(module,'api',side_effect=[release,existing]):
            module.detect()
        assert f'build={expected}\n' in out.read_text()
    with patch.dict(os.environ,{'UPSTREAM_TAG':'$(malicious)'}):
        try: module.detect()
        except ValueError: pass
        else: raise AssertionError('Unsafe tag accepted')
print('Package source checks passed')
