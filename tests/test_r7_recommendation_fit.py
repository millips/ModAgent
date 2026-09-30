import json
from concurrent.futures import ThreadPoolExecutor

from modagent.recommendation_ui import recommendations_from_tool_evidence, recommendation_analysis_text
from modagent.recommendation_fit import assess_goal, enough_alternatives
from modagent import task_control

GOAL = '给我推荐一套优化ui界面 然后能让我在游戏内读到更多信息的mod'
ROWS = [
    {'mod_id': 68, 'name': 'Hentai Hunt', 'summary': 'New UI textures for EMF, cards and books. This mod only replaces textures.', '_detail_verified': True},
    {'mod_id': 159, 'name': 'Hope Phasmophobia Overlay', 'summary': 'Overlay with ghost speed BPM, evidence filtering and timers.', '_detail_verified': True},
    {'mod_id': 187, 'name': 'PhasOverlay', 'summary': 'Overlay with timers and evidence, measures ghost speed.', '_detail_verified': True},
]


def table(rows=ROWS, goal=GOAL):
    return recommendations_from_tool_evidence([('mod_recommend', json.dumps({
        'query': 'UI overhaul interface improvement HUD', 'recommendations': rows,
    })), ('mod_recommend', json.dumps({'query': 'more information display stats ghost info', 'recommendations': rows}))],
        user_goal=goal, game_name='Phasmophobia')


def test_original_report_filters_cosmetics_and_selects_one_alternative():
    result = table()
    assert [i['mod_id'] for i in result['items']] == [159, 187]
    assert len(result['selected_keys']) == 1
    assert all(i['goal_fit']['status'] == 'matched' for i in result['items'])
    assert all(i['alternative_names'] for i in result['items'])
    assert 'Hentai' not in recommendation_analysis_text('untrusted model recommendation Hentai', result)
    assert any(x['reason'] == 'goal_mismatch' for x in result['rejected_candidates'])


def test_chinese_goal_cannot_be_bypassed_by_empty_or_broad_query():
    assert assess_goal(ROWS[0], '优化界面，显示更多信息')['status'] == 'mismatch'
    assert assess_goal(ROWS[1], '优化界面，显示更多信息')['status'] == 'matched'


def test_unrequested_theme_is_allowed_when_user_actually_wants_textures():
    assert assess_goal(ROWS[0], '推荐 UI 贴图换皮')['status'] == 'matched'


def test_detail_verified_is_not_goal_verified():
    result = table(goal='推荐一种尚未描述清楚的新体验')
    assert result['items']
    assert not result['selected_keys']
    assert all(i['goal_fit']['status'] == 'unconfirmed' for i in result['items'])


def test_no_rejected_model_prose_leaks_when_all_results_filtered():
    result = table(ROWS[:1])
    assert not result['items']
    text = recommendation_analysis_text('install Hentai now', result)
    assert 'Hentai' not in text and '不代表' in text


def test_owner_tags_and_negation_are_not_feature_evidence():
    row = {'name': 'Texture pack', 'summary': 'Only textures. Does not provide information display or timers.',
           'author': 'Information HUD', 'tags': ['evidence'], 'url': 'https://example.com/ghost-speed'}
    assert assess_goal(row, GOAL)['status'] == 'mismatch'


def test_cancelled_nested_worker_does_not_report_or_run():
    events=[]
    cancelled=[False]
    with task_control.bind(lambda: cancelled[0]), task_control.observe_progress(events.append):
        first=task_control.scoped_worker(lambda: task_control.report_progress(label='one'))
        late=task_control.scoped_worker(lambda: task_control.report_progress(label='late'))
        with ThreadPoolExecutor() as pool:
            pool.submit(first).result()
            cancelled[0]=True
            try:
                pool.submit(late).result()
            except task_control.TaskCancelled:
                pass
    assert events == [{'label': 'one'}]


def test_nested_workers_share_only_the_owner_read_cache():
    with task_control.observe_progress():
        task_control.read_cache()['fixture']='value'
        with ThreadPoolExecutor() as pool:
            assert pool.submit(task_control.scoped_worker(lambda: task_control.read_cache()['fixture'])).result() == 'value'
    with task_control.observe_progress():
        assert not task_control.read_cache()


def test_alternative_stop_requires_verified_unique_matches_and_respects_count():
    assert enough_alternatives({'recommendations': ROWS}, GOAL)
    assert not enough_alternatives({'recommendations': [ROWS[1], ROWS[1]]}, GOAL)
    assert not enough_alternatives({'recommendations': ROWS}, GOAL + '列出10个')
    assert not enough_alternatives({'recommendations': ROWS}, GOAL + '列出五个')
    assert not enough_alternatives({'recommendations': ROWS}, 'Recommend five mods for UI information overlays')
    assert not enough_alternatives({'recommendations': [{**r, '_detail_verified': False} for r in ROWS]}, GOAL)


def test_nexus_detail_reused_within_owner_not_across_owners(monkeypatch):
    from modagent import tools
    calls=[]
    monkeypatch.setattr(tools.nexus, 'search', lambda *a, **k: [{'mod_id': 159, 'name': 'Hope Overlay'}])
    def detail(mid, *a, **k):
        calls.append(mid)
        return ROWS[1]
    monkeypatch.setattr(tools.nexus, 'get_detail', detail)
    with task_control.observe_progress():
        tools._recommend_nexus('UI', 'fixture', '')
        tools._recommend_nexus('information', 'fixture', '')
    assert calls == [159]
    with task_control.observe_progress():
        tools._recommend_nexus('UI', 'fixture', '')
    assert calls == [159,159]


def test_source_progress_arrives_before_slow_source_finishes(monkeypatch):
    import threading
    from modagent import tools, sources
    from modagent.sources import github
    from modagent.config import Config
    release=threading.Event()
    first=threading.Event()
    events=[]
    monkeypatch.setattr(sources, 'available_sources', lambda *a, **k: {'nexus': 'fixture'})
    monkeypatch.setattr(tools, '_recommend_nexus', lambda *a, **k: {
        'recommendations': ROWS, 'install_plan': [], 'verification': {}})
    def slow(*a, **k):
        assert release.wait(5)
        raise RuntimeError('fixture source unavailable')
    monkeypatch.setattr(github, 'search', slow)
    def receive(event):
        events.append(event)
        if event.get('completed') == 1:
            first.set()
    with task_control.observe_progress(receive):
        with ThreadPoolExecutor() as pool:
            future=pool.submit(task_control.scoped_worker(tools._recommend, 'ui', Config(game_slug='fixture')))
            try:
                assert first.wait(3), events
                assert not future.done()
            finally:
                release.set()
            result=future.result(5)
    assert result['recommendations'] == ROWS
    assert 'github' in result['sources_failed']
    assert set(result['source_elapsed_seconds']) == {'github','nexus'}
    assert all('外部响应' not in e['label'] for e in events)


def test_saved_report_source_wording_not_just_synthetic_keywords():
    actual = [
        {'mod_id':68, 'name':'Hentai Hunt', 'summary':'Add new EMF / Ouija / Tarot Card design / Book Draws / TV Screen',
         'description':"This mod is only a retexture of the tarot / Ouija / EMF / Book / TV Screen. It doesn't affect how the items work.", '_detail_verified':True},
        {'mod_id':159, 'name':'Hope Phasmophobia Overlay',
         'summary':"A transparent, 'Zero-Click' overlay that helps you identify ghosts faster. Features a unique 'Ghost Pacer' (Tap F10 to calculate Speed/BPM), a Smart Smudge Timer, and Hotkey Evidence filtering. No Alt-Tabbing required.", '_detail_verified':True},
        {'mod_id':187, 'name':'PhasOverlay',
         'summary':'An overlay for Phasmophobia that assists you with your investigations. It features a tap-to-speed feature that helps you calculate the ghost speed, multiple timers that can be triggered with F1 - F4, a robust evidence system with tons of information about the ghosts and (soon) a map system.', '_detail_verified':True},
    ]
    result = table(actual)
    assert [i['mod_id'] for i in result['items']] == [159,187]
    assert len(result['selected_keys']) == 1


def test_negative_preferences_do_not_invert_the_goal():
    assert assess_goal(ROWS[1], '不要贴图换皮，只要界面显示更多信息')['status'] == 'matched'
    assert assess_goal(ROWS[0], '不要贴图换皮，只要界面显示更多信息')['status'] == 'mismatch'
    assert assess_goal({'name':'Helper', 'summary':'Overlay with timers without touching the game process.'}, GOAL)['status'] == 'matched'
