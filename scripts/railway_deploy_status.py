import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

q = '{ deployments(input: { serviceId: "' + SID + '", environmentId: "' + EID + '" }) { edges { node { id status createdAt } } } }'
r = requests.post(URL, json={"query": q}, headers=H, timeout=10)
deps = (r.json().get("data") or {}).get("deployments", {}).get("edges", [])
for d in deps[:5]:
    n = d["node"]
    print(f'{n["id"][:12]}  {n["status"]:12}  {n["createdAt"][:19]}')
