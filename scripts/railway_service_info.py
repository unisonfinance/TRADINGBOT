import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

# Check service details including source
q = '''{ service(id: "''' + SID + '''") {
    id name
    repoTriggers { edges { node { repository branch provider } } }
    serviceInstances { edges { node { id environmentId source { repo } } } }
} }'''
r = requests.post(URL, json={"query": q}, headers=H, timeout=10)
print(json.dumps(r.json(), indent=2))

# Also try getting latest deployment details
q2 = '{ deployments(input: { serviceId: "' + SID + '", environmentId: "' + EID + '" }) { edges { node { id status } } } }'
r2 = requests.post(URL, json={"query": q2}, headers=H, timeout=10)
data = r2.json()
deps = (data.get("data") or {}).get("deployments", {}).get("edges", [])
for d in deps[:3]:
    n = d["node"]
    print(f'{n["id"][:12]}  {n["status"]:12}')

# Try to connect service to repo with branch
print("\nConnecting service to repo with branch...")
connect_mut = '''mutation {
  serviceConnect(id: "''' + SID + '''", input: {
    repo: "unisonfinance/TRADINGBOT"
    branch: "master"
  }) { id name }
}'''
r3 = requests.post(URL, json={"query": connect_mut}, headers=H, timeout=10)
print(json.dumps(r3.json(), indent=2))

# Check repo triggers again
q3 = '{ service(id: "' + SID + '") { repoTriggers { edges { node { repository branch provider } } } } }'
r4 = requests.post(URL, json={"query": q3}, headers=H, timeout=10)
print(json.dumps(r4.json(), indent=2))

# Now redeploy
print("\nRedeploying...")
m = 'mutation { serviceInstanceDeploy(serviceId: "' + SID + '", environmentId: "' + EID + '") }'
r5 = requests.post(URL, json={"query": m}, headers=H, timeout=10)
print(json.dumps(r5.json(), indent=2))
