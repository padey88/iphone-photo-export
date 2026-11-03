"""Acceptance tests for the eight-step workflow (fake device, no real deletion)."""
import os
os.environ.setdefault('PATH', '/usr/bin:/bin')
from pathlib import Path
from unittest.mock import patch
import pytest
from test_integrity import roll  # shared isolated device fixture
import app as a
import exporter


@pytest.fixture()
def client(roll, monkeypatch, tmp_path):
    bridge, _, _ = roll
    bridge.disconnect()
    prefs = {"default_dest": "", "favorites": []}
    monkeypatch.setattr(a, 'PREFS', prefs)
    monkeypatch.setattr(a, 'write_prefs', lambda value: None)
    with patch.object(a, 'bridge', bridge):
        for key, value in {'inventory': [], 'classified': [], 'exported_index': {},
                           'dest': tmp_path / 'out', 'job': None, 'last_export': None,
                           'run_id': None, 'job_id': None, 'shutdown_requested': None}.items():
            monkeypatch.setitem(a.STATE, key, value)
        yield a.app.test_client()


def test_workflow(client, roll, tmp_path):
    state = client.get('/api/state').get_json()
    assert state['connected'] is False
    assert state['status_text'] == 'iPhone not detected'
    client.post('/api/connect', json={})
    state = client.get('/api/state').get_json()
    assert all(state['device'].get(k) for k in ('model', 'ios', 'name'))

    dest = tmp_path / 'chosen'
    prefs = client.post('/api/config', json={'dest': str(dest), 'save_default': True, 'favorite': True}).get_json()
    assert prefs['preferences']['default_dest'] == str(dest)
    assert str(dest) in prefs['preferences']['favorites']
    prefs = client.post('/api/config', json={'remove_favorite': str(dest)}).get_json()
    assert str(dest) not in prefs['preferences']['favorites']

    item = client.post('/api/filter', json={'date_mode': 'all', 'kinds': ['photo'], 'keep_pairs': False}).get_json()['items'][0]
    meta = client.get('/api/metadata', query_string={'path': item['path']}).get_json()['metadata']
    assert meta['Filename'] == item['name']
    assert 'Unavailable' in meta['Albums']

    r = client.post('/api/export', json={'paths': [item['path']], 'layout': 'date'})
    assert r.status_code == 200
    a.STATE['job_thread'].join(30)
    assert a.STATE['job']['state'] == 'done'
    result = client.post('/api/verify', json={'paths': [item['path']]}).get_json()
    assert result['ok'] and result['selected_paths'] == [item['path']], (result, a.STATE['job'])
    assert (dest / 'FAKE-DEVICE' / '2023-11' / item['name']).is_file()
    assert client.post('/api/cleanup', json={'paths': [item['path']], 'confirm': 'no'}).status_code == 400
    assert client.post('/api/cleanup', json={'paths': [], 'confirm': 'DELETE'}).status_code == 409
    changed = root = Path(roll[0].fake_root) / item['path'].lstrip('/')
    original = changed.read_bytes()
    changed.write_bytes(original + b'changed after verification')
    blocked = client.post('/api/cleanup', json={'paths': [item['path']], 'confirm': 'DELETE'})
    assert blocked.status_code == 200 and blocked.get_json()['deleted'] == 0
    assert changed.is_file()
    changed.write_bytes(original)
    os.utime(changed, (item['mtime'], item['mtime']))
    result = client.post('/api/cleanup', json={'paths': [item['path']], 'confirm': 'DELETE'})
    assert result.status_code == 200 and result.get_json()['deleted'] == 1
    assert not (Path(roll[0].fake_root) / item['path'].lstrip('/')).exists()
    assert (dest / 'FAKE-DEVICE' / 'CLEANUP.txt').is_file()


def test_unverified_export_never_deletes(client, roll):
    bridge, _, _ = roll
    root = Path(bridge.fake_root)
    client.post('/api/connect', json={})
    original = (root / 'DCIM' / '100APPLE' / 'IMG_1.JPG').read_bytes()
    a.STATE['last_export'] = {'state': 'done', 'safe_to_delete': False,
                              'selected_paths': ['/DCIM/100APPLE/IMG_1.JPG']}
    assert client.post('/api/cleanup', json={'paths': ['/DCIM/100APPLE/IMG_1.JPG'], 'confirm': 'DELETE'}).status_code == 409
    assert (root / 'DCIM' / '100APPLE' / 'IMG_1.JPG').read_bytes() == original


def test_layouts_and_traversal(tmp_path):
    item = {'path': '/DCIM/100APPLE/IMG_0001.HEIC', 'mtime': 0, 'size': 1}
    assert exporter.local_path_for(tmp_path, item['path'], 'category', item).name == 'IMG_0001.HEIC'
    assert exporter.local_path_for(tmp_path, item['path'], 'category', item).parent.name == 'Photos'
    assert exporter.local_path_for(tmp_path, item['path'], 'date', item).parent.name == '1970-01'
    assert exporter.unique_path(tmp_path / 'x').name == 'x'
    (tmp_path / 'x').write_bytes(b'x')
    assert exporter.unique_path(tmp_path / 'x').name == 'x (2)'
    for layout in ('source', 'category', 'date'):
        try:
            exporter.local_path_for(tmp_path, '/DCIM/../outside', layout, item)
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe path accepted')
