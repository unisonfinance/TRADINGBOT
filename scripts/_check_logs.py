import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

# Get project ID
q0 = '{ service(id: "' + SID + '") { projectId } }'
r0 = requests.post(URL, json={"query": q0}, headers=H, timeout=10)
PID = r0.json()["data"]["service"]["projectId"]

# Get deployments
q1 = '{ deployments(first: 3, input: { projectId: "' + PID + '", serviceId: "' + SID + '" }) { edges { node { id status createdAt } } } }'
r1 = requests.post(URL, json={"query": q1}, headers=H, timeout=10)
deps = r1.json()["data"]["deployments"]["edges"]
for d in deps:
    print(d["node"]["id"], d["node"]["status"], d["node"]["createdAt"])

latest_id = deps[0]["node"]["id"]
print(f"\n=== Logs for {latest_id} ===")
q2 = '{ deploymentLogs(deploymentId: "' + latest_id + '", limit: 200) { ... on Log { message severity timestamp } } }'
r2 = requests.post(URL, json={"query": q2}, headers=H, timeout=10)
data2 = r2.json()
if data2.get("data") and data2["data"].get("deploymentLogs"):
    for log in data2["data"]["deploymentLogs"]:
        msg = log.get("message", "")
        print(f"[{log.get('severity','')}] {msg}")
else:
    print("Logs response:", json.dumps(data2, indent=2))
