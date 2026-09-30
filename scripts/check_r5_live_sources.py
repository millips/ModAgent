"""Public-source acceptance: real HTTP, no LLM keys, no game writes."""
import json
import os
from pathlib import Path
import tempfile
import time

os.environ['MODAGENT_DATA_DIR'] = tempfile.mkdtemp(prefix='modagent-r5-public-')
from modagent.sources import github, thunderstore

report = {'real_http': True, 'real_model': False, 'game_writes': False, 'cases': []}
output = Path(__file__).resolve().parents[1] / 'build/chain-reliability-r5/live-sources-v2.json'
output.parent.mkdir(parents=True, exist_ok=True)
cases = [
    ('github', 'Demonologist', 'money', lambda: github.search('money', 'Demonologist', 5)),
    ('github', 'Stardew Valley', 'SMAPI', lambda: github.search('SMAPI', 'Stardew Valley', 5)),
    ('thunderstore', 'repo', 'minimap', lambda: thunderstore.search('repo', 'minimap', 5)),
]
for source, game, query, call in cases:
    started = time.monotonic()
    row = {'source': source, 'game': game, 'query': query}
    try:
        row['results'] = call()
        row['status'] = 'returned' if row['results'] else 'empty'
    except Exception as exc:
        row['status'] = 'failed'
        row['error_type'] = type(exc).__name__
        row['error'] = str(exc)[:300]
    row['seconds'] = round(time.monotonic() - started, 2)
    report['cases'].append(row)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: row[k] for k in ('source', 'game', 'query', 'status', 'seconds')}) , flush=True)
