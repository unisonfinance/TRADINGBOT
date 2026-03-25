import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
PROJECT_ID = "76ef8b25-f7d6-448f-a6ad-103f1490e0e3"
SERVICE_ID = "08df201d-6855-4be9-b2f2-38a7bc18c991"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}",
}
URL = "https://backboard.railway.app/graphql/v2"

# Step 1: Get environment ID
q1 = """{ project(id: "%s") { environments { edges { node { id name } } } } }""" % PROJECT_ID
r1 = requests.post(URL, json={"query": q1}, headers=HEADERS, timeout=10)
print("Environments:", json.dumps(r1.json(), indent=2))

envs = r1.json()["data"]["project"]["environments"]["edges"]
prod_env_id = None
for e in envs:
    if "production" in e["node"]["name"].lower():
        prod_env_id = e["node"]["id"]
        break
if not prod_env_id and envs:
    prod_env_id = envs[0]["node"]["id"]

print(f"\nUsing environment: {prod_env_id}")

# Step 2: Read service_account.json
with open("service_account.json") as f:
    sa_json = f.read().strip()

# Step 3: Upsert variable
mutation = """
mutation variableUpsert($input: VariableUpsertInput!) {
  variableUpsert(input: $input)
}
"""
variables = {
    "input": {
        "projectId": PROJECT_ID,
        "environmentId": prod_env_id,
        "serviceId": SERVICE_ID,
        "name": "FIREBASE_SA_JSON",
        "value": sa_json,
    }
}
r2 = requests.post(URL, json={"query": mutation, "variables": variables}, headers=HEADERS, timeout=15)
print("\nUpsert result:", json.dumps(r2.json(), indent=2))

result = (r2.json().get("data") or {}).get("variableUpsert")
if result:
    print("\n✅ FIREBASE_SA_JSON variable set on Railway!")
elif r2.json().get("errors"):
    print("\n⚠️  Got errors, checking if variable was set anyway...")
    # Read it back to confirm
    q3 = """{ variables(projectId: "%s", environmentId: "%s", serviceId: "%s") }""" % (PROJECT_ID, prod_env_id, SERVICE_ID)
    r3 = requests.post(URL, json={"query": q3}, headers=HEADERS, timeout=10)
    resp3 = r3.json()
    vs = (resp3.get("data") or {}).get("variables") or {}
    if "FIREBASE_SA_JSON" in vs:
        print("✅ Variable IS set on Railway (confirmed by read-back)")
    else:
        print("❌ Variable NOT found. Available vars:", list(vs.keys()))
        print("  Full response:", json.dumps(resp3, indent=2))
else:
    print("\n❌ Failed to set variable")
