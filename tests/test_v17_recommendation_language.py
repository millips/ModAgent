import os
import re
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent.recommendation_ui import recommendation_analysis_text


@pytest.mark.parametrize('empty', [True, False])
def test_english_recommendation_preserves_states_and_dependencies(empty):
    payload = {'goal_reviewed': True, 'items': []}
    if not empty:
        payload.update(items=[
            {'name': 'Fixture skin', 'source': 'nexus', 'mod_id': 123, 'selection_key': 'nexus:123',
             'version': '1.0', 'detail_verified': True, 'dependencies': ['Loader'],
             'goal_fit': {'status': 'matched'}},
            {'name': 'Loader', 'source': 'workshop', 'source_label': 'Steam 创意工坊',
             'source_id': '456', 'is_prerequisite': True, 'required_by': ['Fixture skin'],
             'verification_status': 'blocked', 'goal_fit': {'status': 'unknown'}},
        ], selected_keys=['nexus:123'], dependency_requirements=[
            {'name': 'Loader', 'required_by': ['Fixture skin'], 'status': 'needs_resolution'},
            {'name': 'Unrelated', 'required_by': ['Other'], 'status': 'unresolved'},
        ], source_counts={'nexus': 1, 'workshop': 1})
    result = recommendation_analysis_text('', payload, language='en')
    assert not re.search(r'[\u4e00-\u9fff]', result)
    if empty:
        assert 'No candidates' in result and 'does not mean' in result
    else:
        assert 'Fixture skin' in result and 'Loader' in result and 'Unrelated' not in result
        assert 'Nexus #123' in result and 'Steam Workshop 456' in result
        assert '1.0' in result and 'blocked' in result and 'not yet eligible' in result
        assert 'Source details verified' in result and 'package' in result
        assert 'No feature description' in result
