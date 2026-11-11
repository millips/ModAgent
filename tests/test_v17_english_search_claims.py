import json
import os
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent.report_validator import validate_search_report, build_search_fallback


def evidence():
    return [{'role': 'assistant', 'tool_calls': [{'id': 's', 'function': {'name': 'mod_recommend'}}]},
            {'role': 'tool', 'tool_call_id': 's', 'content': json.dumps({
                'sources_attempted': ['nexus', 'github'], 'sources_consulted': ['nexus'],
                'sources_empty': ['nexus'], 'sources_failed': {'github': 'timeout'},
                'sources_skipped': {'gamebanana': {}, 'workshop': {}, 'thunderstore': {}},
            })}]


@pytest.mark.parametrize('text', [
    'I searched GitHub.', 'GitHub was searched.', 'We have checked GameBanana.',
    'Nexus has no mods.', 'There are no mods on Nexus.', 'This mod is not available on GitHub.',
    'We searched all sources.', 'All sources were checked.', 'There are no mods anywhere.',
    'This does not prove anything. GitHub was searched.',
])
def test_unsupported_english_claims_are_rejected(text):
    assert not validate_search_report(text, evidence()).ok


@pytest.mark.parametrize('text', [
    'I searched Nexus. GitHub search failed.',
    'Nexus was searched; no matching results this time.',
    'I have not searched GitHub.', 'GitHub has not been searched.',
    'This does not prove there are no mods on Nexus.',
    'An empty result does not mean this mod is not available on GitHub.',
    'Not all sources were checked.', 'No matching results were returned by Nexus.',
])
def test_cautious_or_supported_english_claims_remain_allowed(text):
    assert validate_search_report(text, evidence()).ok


def test_english_fallback_satisfies_its_own_evidence_rules():
    assert validate_search_report(build_search_fallback(evidence(), language='en'), evidence()).ok


def test_checking_all_sources_does_not_prove_universal_absence():
    records = evidence()
    payload = json.loads(records[-1]['content'])
    payload['sources_consulted'] = ['nexus', 'github', 'gamebanana', 'thunderstore', 'workshop']
    payload['sources_empty'] = payload['sources_consulted']
    payload['sources_failed'] = {}
    records[-1]['content'] = json.dumps(payload)
    assert validate_search_report('We searched all sources.', records).ok
    assert not validate_search_report('There are no mods anywhere.', records).ok
