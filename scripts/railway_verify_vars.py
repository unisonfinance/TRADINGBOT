import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
PID = "d8914cb8-5dc8-4d62-9de4-d3f7bb0a7332"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

q = '{ variables(projectId: "' + PID + '", environmentId: "' + EID + '", serviceId: "' + SID + '") }'
r = requests.post(URL, json={"query": q}, headers=H, timeout=10)
vs = (r.json().get("data") or {}).get("variables") or {}
print(f"Total vars: {len(vs)}")
for k in sorted(vs.keys()):
    v = str(vs[k])
    if len(v) > 30:
        v = v[:30] + "..."
    print(f"  {k} = {v}")
