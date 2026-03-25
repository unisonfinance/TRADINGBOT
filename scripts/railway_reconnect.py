import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

# 1) Reconnect service to GitHub with branch
print("1. Reconnecting service to GitHub repo + branch...")
mut = """
mutation serviceConnect($id: String!, $input: ServiceConnectInput!) {
    serviceConnect(id: $id, input: $input) {
        id name
    }
}"""
variables = {
    "id": SID,
    "input": {
        "repo": "unisonfinance/TRADINGBOT",
        "branch": "master"
    }
}
r = requests.post(URL, json={"query": mut, "variables": variables}, headers=H, timeout=10)
print(json.dumps(r.json(), indent=2))

# 2) Check if repo triggers exist now
print("\n2. Checking repo triggers...")
q = '{ service(id: "' + SID + '") { repoTriggers { edges { node { repository branch } } } } }'
r2 = requests.post(URL, json={"query": q}, headers=H, timeout=10)
print(json.dumps(r2.json(), indent=2))

# 3) Force a new deployment
print("\n3. Triggering deploy...")
m = 'mutation { serviceInstanceDeploy(serviceId: "' + SID + '", environmentId: "' + EID + '") }'
r3 = requests.post(URL, json={"query": m}, headers=H, timeout=10)
print(json.dumps(r3.json(), indent=2))
