"""Offline audit; temporary state, stub tools, no network or game writes."""
import ast, json, os, sys, tempfile, threading, urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

def main():
    out = {}
    out['metrics'] = []
    for name in ['modagent/agent.py','modagent/tools.py','modagent/api.py','modagent/prompts.py','modagent/default_prompt.md','modagent/recommendation_ui.py','electron/src/components/ChatPage.jsx']:
        text = (ROOT/name).read_text(encoding='utf-8-sig')
        row = dict(file=name, lines=len(text.splitlines()), chars=len(text))
        if name.endswith('.py'):
            row['largest_functions'] = sorted([(n.name,n.lineno,n.end_lineno-n.lineno+1) for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))],key=lambda x:x[2],reverse=True)[:3]
        out['metrics'].append(row)
    out['test_files'] = len(list((ROOT/'tests').glob('test_*.py')))
    with tempfile.TemporaryDirectory(prefix='modagent-audit-') as temp:
        os.environ['MODAGENT_DATA_DIR'] = temp
        from modagent import db, tools, prompts, agent as am
        from modagent.config import Config
        from modagent.orchestration import store
        from modagent.orchestration.models import TaskSpec, AgentMode
        from modagent.orchestration.runtime import AgentCoreRuntime
        from modagent.orchestration.router import route_message
        from modagent.orchestration.policies import allowed_tools, SOURCE_RESOLUTION_TOOLS
        from modagent.orchestration.prompting import build_v2_prompt
        from modagent.recommendation_ui import _matches_source_query, recommendations_from_tool_evidence
        from modagent.sources.github import _filter_game_mod_results
        from evals.runner import run_deterministic
        from evals.variants import CASES_1000
        db.DB_FILE = os.path.join(temp,'state.db')
        db.init_db()
        def runtime(mode=AgentMode.SEARCH_EXACT, feature='on', **kwargs):
            spec = TaskSpec.create(session_id='audit',game_id='fixture',intent=mode,user_goal='audit fixture',**kwargs)
            r = AgentCoreRuntime(spec,feature_mode=feature)
            r.start()
            return r
        out['eval120'] = run_deterministic()
        out['eval1000'] = run_deterministic(CASES_1000)
        out['prompt'] = {}
        for count in [0,100,1000]:
            mods = [SimpleNamespace(name=f'Example Mod {i}',version='1.0',load_order=i) for i in range(count)]
            with patch.object(db,'get_installed_mods',return_value=mods):
                out['prompt'][f'legacy_{count}_mods_chars'] = len(prompts.build_prompt(Config()))
        for tier in ['free','pro']:
            defs = tools.build_tools_definitions(tier)
            out['prompt'][tier+'_schema_chars'] = len(json.dumps(defs,ensure_ascii=False))
            out['prompt'][tier+'_tools'] = len(defs)
        out['routes'] = []
        for text in ['不要帮我更新，我只是想知道全部更新是什么意思','为什么检查更新会失败？先别更新','分享码是什么意思？','推荐一个能改钱的mod，不要别的功能','有哪些 eve 的换皮但是是别的游戏动漫 IP，比如 FF7 Tifa','创建一个快照','禁用我选中的这个mod','How do I check for updates without installing anything?']:
            route = route_message(text)
            spec = TaskSpec.create(session_id='audit',game_id='fixture',intent=route.intent,user_goal=text,authorization={'install':route.install_authorized})
            out['routes'].append(dict(input=text,intent=route.intent.value,confidence=route.confidence,install_authorized=route.install_authorized,tools=sorted(allowed_tools(spec))))
        r = runtime()
        r.tool_finished('nexus_search',{'query':'Tifa'},'{"error":"timeout"}',False)
        r.finalize_from_text('搜索失败，请稍后重试。')
        out['failed_tool_with_text'] = store.get_task(r.spec.task_id)['outcome']
        r = runtime()
        r.finalize_from_text('')
        out['empty_no_evidence'] = store.get_task(r.spec.task_id)['outcome']
        r = runtime(AgentMode.EXECUTE_PLAN,authorization={'install':True})
        out['variant_key_collision'] = r.idempotency_key('mod_download',{'mod_id':'390','file_id':'11'}) == r.idempotency_key('mod_download',{'mod_id':'390','file_id':'12'})
        out['batch_key_collision'] = r.idempotency_key('batch_download',{'mods':[{'mod_id':'1'}]}) == r.idempotency_key('batch_download',{'mods':[{'mod_id':'2'}]})
        r.spec.authorization['destructive'] = True
        out['frozen_spec_mutable'] = r.spec.authorization['destructive']
        r = runtime()
        r.cancel('audit cancellation')
        r.tool_finished('nexus_search',{'query':'late'},'{"items":[]}',True)
        out['events_after_cancel'] = [e['type'] for e in store.list_events(r.spec.task_id)]
        out['checkpoint_after_cancel'] = bool(store.get_task(r.spec.task_id)['checkpoint'])
        calls=[]
        def fake(name,args,cfg):
            calls.append((name,args))
            return '{"status":"completed"}'
        r = runtime(AgentMode.EXECUTE_PLAN,feature='shadow',authorization={'install':True})
        a = am.Agent(Config())
        a._core_runtime,a._core_spec = r,r.spec
        with patch.object(am,'execute',side_effect=fake):
            a._exec('tool_extract',{'local_path':'fixture.zip','display_name':'Tool One'})
            second=json.loads(a._exec('tool_extract',{'local_path':'fixture.zip','display_name':'Tool Two'}))
        out['shadow_changes_execution'] = dict(stub_calls=len(calls),second_result=second)
        r=runtime(AgentMode.EXECUTE_PLAN,authorization={'install':True},targets=[{'mod_id':'42'}])
        a=am.Agent(Config())
        a._core_runtime,a._core_spec=r,r.spec
        calls.clear()
        with patch.object(am,'execute',side_effect=fake):
            result=json.loads(a._exec('mod_download',{'mod_id':'999','file_id':'777'}))
        out['spec_target_without_legacy_selection']=dict(stub_called=bool(calls),result=result)
        release,entered,done=threading.Event(),threading.Event(),threading.Event()
        effects=[]
        def slow(name,args,cfg):
            entered.set()
            release.wait(2)
            effects.append('simulated write after timeout')
            done.set()
            return '{"status":"completed"}'
        a=am.Agent(Config())
        with patch.object(am,'TOOL_TIMEOUT_S',.03),patch.object(am,'execute',side_effect=slow):
            result=json.loads(a._exec('tool_extract',{'local_path':'fixture.zip'}))
            out['timeout_worker']=dict(result=result,entered=entered.is_set(),done_at_return=done.is_set())
            release.set()
            done.wait(2)
        out['timeout_worker']['late_simulated_effect']=effects
        r=runtime(AgentMode.EXECUTE_PLAN,authorization={'install':True})
        a=am.Agent(Config())
        a._core_runtime,a._core_spec=r,r.spec
        with patch.object(am,'execute',return_value='{ "status":"manual_action_required", "message":"please log in" }'):
            a._exec('mod_download',{'mod_id':'390','file_id':'11'})
        out['manual_gate_recorded_as_completed_effect']=bool(r.completed_effect('mod_download',{'mod_id':'390','file_id':'11'}))
        r=runtime()
        a=am.Agent(Config())
        def broken_stream():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='partial text',tool_calls=None))])
            raise TimeoutError('simulated SSE read timeout')
        try:
            with patch.object(a,'_stream',return_value=broken_stream()):
                list(a.chat_stream('帮我找 Tifa',task_spec=r.spec,core_runtime=r,core_mode='on'))
        except TimeoutError:
            r.fail('simulated API exception handler',retryable=True)
        out['midstream_failure_outcome']=store.get_task(r.spec.task_id)['outcome']
        out['resolve_intersection']=sorted(SOURCE_RESOLUTION_TOOLS & am.RESOLUTION_READONLY_TOOLS)
        out['http_transient']={str(c):tools._is_transient_source_error(urllib.error.HTTPError('https://example.invalid',c,'denied',{},None)) for c in [401,403,404,500]}
        out['relevance']={
            'partial_match':_matches_source_query({'name':'EVE Makeup'},'EVE Tifa','Stellar Blade'),
            'chinese_no_filter':_matches_source_query({'name':'Fast Intro'},'蒂法换皮','Stellar Blade'),
            'github_owner_as_game':bool(_filter_game_mod_results([{'name':'money-mod','full_name':'DemonologistFan/money-mod','summary':'A money mod for Zanzarah'}],'money','Demonologist'))}
        with patch.object(db,'get_installed_mods',return_value=[]):
            payload=recommendations_from_tool_evidence([('github_search',{'query':'money','results':[{'name':'Money mod','full_name':'author/money-mod','url':'https://github.com/author/money-mod','summary':'Money mod for Zanzarah','game_slug':'zanzarah'}]})],game_slug='demonologist',game_name='Demonologist')
        out['relevance']['central_wrong_game_rows']=len(payload.get('items',[]))
        out['requests']=[]
        for msg,mode,action,rows in [('什么是 mod？','off','',[]),('什么是 mod？','on','',[]),('补齐详情','on','resolve',[{'source':'github','source_id':'author/mod','url':'https://github.com/author/mod','name':'Test'}]),('创建一个快照','on','',[])]:
            route=route_message(msg,selection_action=action,has_selection=bool(rows))
            spec=TaskSpec.create(session_id='audit',game_id='fixture',intent=route.intent,user_goal=msg,targets=rows,confidence=route.confidence,authorization={'install':route.install_authorized})
            a=am.Agent(Config())
            def capture(messages,definitions):
                out['requests'].append(dict(input=msg,mode=mode,action=action,system_chars=sum(len(m.get('content','')) for m in messages if m['role']=='system'),tools=[d['function']['name'] for d in definitions]))
                raise RuntimeError('audit stopped before network')
            with patch.object(a,'_stream',side_effect=capture):
                list(a.chat_stream(msg,task_spec=spec,core_mode=mode,selection_action=action,recommendation_selection=rows))
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
