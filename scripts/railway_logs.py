import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
PID = "c4c888c6-3be7-4b9c-b491-593fd860407d"  # authentic-forgiveness
SID = "39f7207d-9294-4427-a073-e5e17fe49648"  # web

# Get deployments
q1 = '{ deployments(first: 3, input: { projectId: "' + PID + '", serviceId: "' + SID + '" }) { edges { node { id status createdAt } } } }'
r1 = requests.post(URL, json={"query": q1}, headers=HEADERS, timeout=10)
deps = r1.json()["data"]["deployments"]["edges"]
for d in deps:
    print(d["node"]["id"], d["node"]["status"], d["node"]["createdAt"])

# Get logs for the crashed one
crashed_id = deps[0]["node"]["id"]
print(f"\nFetching logs for {crashed_id}...")

q2 = '{ deploymentLogs(deploymentId: "' + crashed_id + '", limit: 100) { ... on Log { message severity timestamp } } }'
r2 = requests.post(URL, json={"query": q2}, headers=HEADERS, timeout=10)
data2 = r2.json()
if data2.get("data") and data2["data"].get("deploymentLogs"):
    for log in data2["data"]["deploymentLogs"]:
        print(f"[{log.get('severity','')}] {log.get('message','')}")
else:
    print("Logs response:", json.dumps(data2, indent=2))

# Also try build logs
q3 = '{ buildLogs(deploymentId: "' + crashed_id + '", limit: 50) { ... on Log { message } } }'
r3 = requests.post(URL, json={"query": q3}, headers=HEADERS, timeout=10)
data3 = r3.json()
if data3.get("data") and data3["data"].get("buildLogs"):
    print("\n=== BUILD LOGS ===")
    for log in data3["data"]["buildLogs"]:
        print(log.get("message", ""))
else:
    print("\nBuild logs response:", json.dumps(data3, indent=2))
