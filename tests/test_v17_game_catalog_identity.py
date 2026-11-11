import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import nexus


@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('tail', [None, 'invalid catalogue row'])
def test_catalog_identity_is_from_selected_row(monkeypatch, position, tail):
    rows = [
        {'name':'Other Game', 'domain_name':'othergame', 'id':900},
        {'name':'Another Game', 'domain_name':'anothergame', 'id':901},
    ]
    rows.insert(position, {'name':'Fixture Adventures', 'domain_name':'fixtureadventures', 'id':123})
    if tail:
        rows.append(tail)
    monkeypatch.setattr(nexus, '_GAME_DISCOVERY_CACHE', {})
    monkeypatch.setattr(nexus, '_api', lambda *_: rows)
    found = nexus.discover_game('Fixture Adventures', nexus_api_key='synthetic')
    assert found['status'] == 'available', found
    assert found['slug'] == 'fixtureadventures'
    assert found['game_id'] == 123
    assert 'Fixture Adventures' in found['evidence']
    monkeypatch.setattr(nexus, '_api', lambda *_: pytest.fail('Second read should reuse validated identity'))
    assert nexus.discover_game('Fixture Adventures', nexus_api_key='synthetic') == found


def test_missing_selected_id_does_not_borrow_unrelated_id():
    found = nexus._match_game_catalog('Fixture Adventures', [
        {'name':'Fixture Adventures', 'domain_name':'fixtureadventures'},
        {'name':'Other Game', 'domain_name':'othergame', 'id':900},
    ])
    assert found['slug'] == 'fixtureadventures'
    assert found['game_id'] == 0
