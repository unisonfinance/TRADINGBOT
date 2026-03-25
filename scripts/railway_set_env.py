import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
PID = "d8914cb8-5dc8-4d62-9de4-d3f7bb0a7332"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

# Read .env file and extract all EXCHANGE_ vars
env_vars = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()

print(f"Found {len(env_vars)} env vars:")
for k, v in env_vars.items():
    display = v[:20] + "..." if len(v) > 20 else v
    print(f"  {k} = {display}")

mutation = """mutation variableUpsert($input: VariableUpsertInput!) { variableUpsert(input: $input) }"""

print("\nSetting variables on Railway...")
for name, value in env_vars.items():
    variables = {
        "input": {
            "projectId": PID,
            "environmentId": EID,
            "serviceId": SID,
            "name": name,
            "value": value,
        }
    }
    r = requests.post(URL, json={"query": mutation, "variables": variables}, headers=HEADERS, timeout=10)
    ok = (r.json().get("data") or {}).get("variableUpsert")
    status = "✅" if ok else "❌"
    print(f"  {status} {name}")

# Verify
q = '{ variables(projectId: "' + PID + '", environmentId: "' + EID + '", serviceId: "' + SID + '") }'
r2 = requests.post(URL, json={"query": q}, headers=HEADERS, timeout=10)
vs = (r2.json().get("data") or {}).get("variables") or {}
print(f"\nTotal Railway variables now: {len(vs)}")
for k in sorted(vs.keys()):
    v = str(vs[k])
    if len(v) > 30: v = v[:30] + "..."
    print(f"  {k} = {v}")
