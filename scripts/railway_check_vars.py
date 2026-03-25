import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
PID = "c4c888c6-3be7-4b9c-b491-593fd860407d"
SID = "39f7207d-9294-4427-a073-e5e17fe49648"
EID = "e1dac481-b053-4c55-8fd0-dfb76ecbc9d5"

q = '{ variables(projectId: "' + PID + '", environmentId: "' + EID + '", serviceId: "' + SID + '") }'
r = requests.post(URL, json={"query": q}, headers=HEADERS, timeout=10)
vs = (r.json().get("data") or {}).get("variables") or {}
print(f"Total variables: {len(vs)}")
for k in sorted(vs.keys()):
    v = str(vs[k])
    if len(v) > 60:
        v = v[:60] + "..."
    print(f"  {k} = {v}")

if "PORT" not in vs:
    print("\n⚠️  PORT is NOT set! Adding PORT=5050...")
    mutation = """mutation variableUpsert($input: VariableUpsertInput!) { variableUpsert(input: $input) }"""
    variables = {
        "input": {
            "projectId": PID,
            "environmentId": EID,
            "serviceId": SID,
            "name": "PORT",
            "value": "5050",
        }
    }
    r2 = requests.post(URL, json={"query": mutation, "variables": variables}, headers=HEADERS, timeout=15)
    print("Result:", json.dumps(r2.json(), indent=2))
