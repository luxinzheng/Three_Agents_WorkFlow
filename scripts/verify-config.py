import json

with open(r'C:\Users\Administrator\.openclaw\openclaw.json', encoding='utf-8') as f:
    cfg = json.load(f)

expected_agents = {'zhongshusheng', 'shangshusheng', 'menxiasheng'}
found_agents = set()

for a in cfg['agents']['list']:
    aid = a.get('id', '')
    if aid in expected_agents:
        found_agents.add(aid)
    sa = a.get('subagents', {}).get('allowAgents', [])
    has_sub = 'subagents' in a
    if sa:
        print(f'{aid}: allowAgents={sa}')
    else:
        print(f'{aid}: allowAgents=NONE, has_subagents_key={has_sub}')

missing = expected_agents - found_agents
if missing:
    print(f'\nWARNING: Missing agents: {missing}')
else:
    print(f'\nOK: All 3 agents found ({", ".join(sorted(found_agents))})')
