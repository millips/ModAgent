"""Process-status replies come from recorded events, never model recollection."""
import re
from modagent import db
from . import store
from .policies import SEARCH_TOOLS, MUTATING_TOOLS

def is_process_question(message: str) -> bool:
    text = str(message or '').strip()
    if re.fullmatch(r'[?？]+', text):
        return True
    text = text.strip('？?。.!！ \t\r\n')
    return bool(re.fullmatch(
        r'刚才发生了什么|刚才(?:你)?(?:做了什么|干了什么)|你刚才(?:做了什么|干了什么)|'
        r'何意味|什么意思|(?:我)?没看懂|(?:我)?看不懂|(?:所以)?(?:现在)?是什么情况|'
        r'what just happened|what did you just do|what does that mean|i don.t understand', text, re.I))

def process_report(session_id: str, game_id: str, language: str = 'zh-CN') -> str:
    en = language.startswith('en')
    conn = db.get_conn()
    try:
        # Repeated follow-ups must keep explaining the operation, not the prior
        # explanation turn. This also keeps other sessions/games out of scope.
        row = conn.execute("SELECT task_id FROM agent_tasks WHERE session_id=? AND game_id=? AND intent != 'CHAT_EXPLAIN' ORDER BY created_at DESC LIMIT 1",
                           (session_id, game_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return ('No previous task record is available for this session and game. I cannot confirm what ran. This reply does not resume any task.' if en else
                '当前没有可核验的操作记录。你是想问上一句说明，还是某个按钮怎么用？指出不清楚的那一处即可；本轮不恢复搜索、下载或安装。')
    task = store.get_task(row[0]) or {}
    events = store.list_events(row[0])
    started = [e.get('payload', {}) for e in events if e['type'] == 'tool_started']
    finished = [e.get('payload', {}) for e in events if e['type'] == 'tool_finished']
    searches = sum(e.get('tool') in SEARCH_TOOLS for e in started)
    returned = sum(e.get('tool') in SEARCH_TOOLS and e.get('ok') is True for e in finished)
    writes = sum(e.get('tool') in MUTATING_TOOLS for e in started)
    state = str(task.get('state', 'UNKNOWN'))
    if state == 'WAITING_CONFIRMATION':
        if en:
            return ('The previous task stopped at review, waiting for confirmation; that is not an installation receipt. '
                    'Use “View pending selection” on the result card to return to the selected items. '
                    'If no confirmation control is available, the interface is not ready; do not type an installation command to bypass it. '
                    'This reply does not resume searching, downloading or installing.')
        return ('意思是：上一轮停在清单核验后的“等待确认”，不是已经安装成功。'
                '请点结果卡上的“查看待确认清单”，回到原来勾选的那张表核对。'
                '如果没有确认按钮，说明界面还没有准备好，不能靠再发“确认安装”绕过去。'
                '本轮只解释现有记录，不恢复搜索、下载或安装。')
    # Do not quote free-form stored summaries, file paths, or model prose.
    if en:
        return (f'From the recorded events: {searches} search steps started and {returned} have successful receipts. '
                f'{writes} write-capable tool steps started; this does not prove installation completed. '
                f'The recorded task state is {state}. '
                'A cancellation record is not proof that all in-flight work has stopped. This reply does not resume searching, downloading or installing.')
    labels = {'COMPLETED':'已结束', 'PARTIAL':'部分完成', 'CANCELLED':'已取消', 'BLOCKED':'受阻',
              'FAILED':'失败', 'GATHERING':'收集信息中', 'EXECUTING':'执行中', 'WAITING_CONFIRMATION':'等待确认'}
    return (f'按任务事件记录：上一任务启动了 {searches} 个搜索步骤，其中 {returned} 个有成功返回记录；这不等于候选满足需求。'
            f'记录到 {writes} 个可能写入的工具步骤启动，不能仅据此判断安装是否完成。'
            f'任务记录状态：{labels.get(state, "尚未确认结束")}。'
            '取消记录只表示已请求停止，不能据此保证所有在途操作都已退出。'
            '本轮只说明已有记录，不恢复搜索、下载或安装。')
