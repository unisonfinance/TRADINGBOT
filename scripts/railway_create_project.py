import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"

# Step 1: Create project
print("1. Creating project 'TRADINGBOT'...")
mutation1 = """
mutation {
  projectCreate(input: { name: "TRADINGBOT" }) {
    id
    name
    environments { edges { node { id name } } }
  }
}
"""
r1 = requests.post(URL, json={"query": mutation1}, headers=HEADERS, timeout=15)
data1 = r1.json()
print(json.dumps(data1, indent=2))

project = data1["data"]["projectCreate"]
PROJECT_ID = project["id"]
ENV_ID = project["environments"]["edges"][0]["node"]["id"]
print(f"\n   Project ID: {PROJECT_ID}")
print(f"   Env ID:     {ENV_ID}")

# Step 2: Create service from GitHub repo
print("\n2. Creating service from unisonfinance/TRADINGBOT...")
mutation2 = """
mutation {
  serviceCreate(input: {
    projectId: "%s"
    name: "web"
    source: { repo: "unisonfinance/TRADINGBOT" }
  }) {
    id
    name
  }
}
""" % PROJECT_ID
r2 = requests.post(URL, json={"query": mutation2}, headers=HEADERS, timeout=15)
data2 = r2.json()
print(json.dumps(data2, indent=2))

service = (data2.get("data") or {}).get("serviceCreate")
if not service:
    print("⚠️  Service creation failed. You may need to connect the repo manually in Railway dashboard.")
    print("   Go to: railway.app → project → + New Service → GitHub Repo → unisonfinance/TRADINGBOT")
else:
    SERVICE_ID = service["id"]
    print(f"   Service ID: {SERVICE_ID}")

    # Step 3: Set FIREBASE_SA_JSON variable
    print("\n3. Setting FIREBASE_SA_JSON variable...")
    with open("service_account.json") as f:
        sa_json = f.read().strip()

    mutation3 = """mutation variableUpsert($input: VariableUpsertInput!) { variableUpsert(input: $input) }"""
    variables3 = {
        "input": {
            "projectId": PROJECT_ID,
            "environmentId": ENV_ID,
            "serviceId": SERVICE_ID,
            "name": "FIREBASE_SA_JSON",
            "value": sa_json,
        }
    }
    r3 = requests.post(URL, json={"query": mutation3, "variables": variables3}, headers=HEADERS, timeout=15)
    data3 = r3.json()
    if (data3.get("data") or {}).get("variableUpsert"):
        print("   ✅ FIREBASE_SA_JSON set!")
    else:
        print("   ⚠️  Variable set may have failed:", json.dumps(data3, indent=2))

    # Step 4: Generate a domain
    print("\n4. Generating public domain...")
    mutation4 = """
    mutation {
      serviceInstanceDeploy(serviceId: "%s", environmentId: "%s") 
    }
    """ % (SERVICE_ID, ENV_ID)
    r4 = requests.post(URL, json={"query": mutation4}, headers=HEADERS, timeout=15)
    print("   Deploy triggered:", json.dumps(r4.json(), indent=2))

print("\n🎉 Done! Check railway.app for your new project.")
