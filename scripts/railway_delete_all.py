import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"

# Get all projects
r = requests.post(URL, json={"query": "{ projects { edges { node { id name } } } }"}, headers=HEADERS, timeout=10)
projects = r.json()["data"]["projects"]["edges"]

print(f"Found {len(projects)} projects:\n")
for p in projects:
    print(f"  - {p['node']['name']} ({p['node']['id']})")

print("\n--- Deleting all projects ---\n")
for p in projects:
    pid = p["node"]["id"]
    name = p["node"]["name"]
    mutation = 'mutation { projectDelete(id: "' + pid + '") }'
    r2 = requests.post(URL, json={"query": mutation}, headers=HEADERS, timeout=10)
    data = r2.json()
    if (data.get("data") or {}).get("projectDelete"):
        print(f"  ✅ Deleted: {name}")
    else:
        err = (data.get("errors") or [{}])[0].get("message", "unknown error")
        print(f"  ❌ Failed to delete {name}: {err}")

# Verify
r3 = requests.post(URL, json={"query": "{ projects { edges { node { id name } } } }"}, headers=HEADERS, timeout=10)
remaining = r3.json()["data"]["projects"]["edges"]
print(f"\nRemaining projects: {len(remaining)}")
