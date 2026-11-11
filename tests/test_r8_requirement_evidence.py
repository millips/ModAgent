"""Requirements and evidence are not permissions or claims of compatibility."""
import pytest

from dataclasses import FrozenInstanceError
from modagent.recommendation_fit import assess_goal, compile_goal
from modagent.recommendation_ui import normalize_recommendations, promote_verified_recommendation


def test_title_alone_does_not_prove_requested_function():
    result = assess_goal({'name': 'Money UI Timer', 'description': ''}, 'money mod')
    assert result['status'] == 'unconfirmed'


def test_excluded_appearance_is_not_silently_accepted():
    result = assess_goal({'name': 'Theme', 'summary': 'UI textures plus an evidence timer overlay.'},
                         '显示更多信息，不要贴图换皮')
    assert result['status'] == 'mismatch'
    assert 'appearance' in result['excluded_matches']


def test_no_evidence_is_not_proof_of_mismatch():
    result = assess_goal({'name': 'Mystery', 'summary': 'Read the release page for details.'}, '更多信息')
    assert result['status'] == 'unconfirmed'
    assert not result['evidence']


@pytest.mark.parametrize('text', ['Gold coin textures for your UI.', 'Shows your money balance in the HUD.'])
def test_money_mention_does_not_prove_a_money_modifier(text):
    result = assess_goal({'name': 'Money Helper', 'summary': text}, '有没有金钱修改器')
    assert result['status'] != 'matched'


@pytest.mark.parametrize('text', ['Allows you to edit money and currency values.', '可修改金钱数量。'])
def test_money_modifier_with_actual_function_evidence(text):
    assert assess_goal({'summary': text}, '有没有金钱修改器')['status'] == 'matched'


def test_specific_function_not_satisfied_by_a_different_information_feature():
    result = assess_goal({'summary': 'An evidence overlay with ghost speed information.'},
                         '需要显示更多信息，特别是计时器')
    assert result['status'] != 'matched'


def test_planned_feature_not_counted_as_current():
    result = assess_goal({'name': 'UI Timer', 'summary': 'Timers are planned. Currently only textures.'},
                         '显示更多信息，带计时器')
    assert result['status'] != 'matched'


def test_requirements_are_immutable_and_preserve_goal_and_constraints():
    goal = '推荐 3 个显示更多信息的工具，要计时器，不要贴图'
    spec = compile_goal(goal)
    assert spec.original_goal == goal
    assert spec.required == ('information',)
    assert spec.excluded == ('appearance',)
    assert spec.required_features == ('timer',)
    assert spec.requested_count == 3
    with pytest.raises(FrozenInstanceError):
        spec.original_goal = 'install everything'
    assert assess_goal({'summary': 'An evidence timer overlay.'}, spec)['status'] == 'matched'


def test_fresh_detail_cannot_inherit_old_generated_feature_proof():
    payload = normalize_recommendations({'recommendations': [{
        'mod_id': 42, 'name': 'Helper', 'summary': 'An information overlay with timers.'}]},
        user_goal='显示更多信息，计时器')
    key = payload['items'][0]['selection_key']
    payload['wanted_keys'] = [key]
    updated = promote_verified_recommendation(payload, 'nexus', {
        'mod_id': 42, 'description': 'Only textures. Does not provide timers.'})
    assert updated['items'][0]['goal_fit']['status'] == 'mismatch'
    assert updated['items'][0]['resolution_kind'] == 'goal_mismatch'
    assert 'information overlay with timers' not in updated['items'][0]['content']
    assert key not in updated['selected_keys']


def test_requested_count_caps_automatic_selection():
    payload = normalize_recommendations({'recommendations': [
        {'mod_id': mid, 'name': f'Theme {mid}', 'summary': 'New UI textures.', '_detail_verified': True}
        for mid in range(1, 5)]}, user_goal='推荐 2 个 UI 贴图')
    assert payload['requirements']['requested_count'] == 2
    assert len(payload['selected_keys']) == 2


def test_empty_new_detail_does_not_auto_promote_wanted_candidate():
    payload = normalize_recommendations({'recommendations': [{
        'mod_id': 42, 'name': 'Helper', 'summary': 'An evidence overlay with timers.'}]},
        user_goal='显示更多信息')
    key = payload['items'][0]['selection_key']
    payload['wanted_keys'] = [key]
    updated = promote_verified_recommendation(payload, 'nexus', {'mod_id': 42, 'version': '1'})
    assert updated['items'][0]['goal_fit']['status'] == 'unconfirmed'
    assert key not in updated['selected_keys']
