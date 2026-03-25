import requests, json

TOKEN = "f5c46c67-c920-49dc-bb55-98b19d783166"
H = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
URL = "https://backboard.railway.app/graphql/v2"
SID = "e0411e22-8741-4182-aeba-6c12d4a4b065"
EID = "3c12a4d7-bf19-4303-b1f7-88fbeea06e89"

mutation = """mutation { serviceInstanceDeploy(serviceId: "%s", environmentId: "%s") }""" % (SID, EID)
r = requests.post(URL, json={"query": mutation}, headers=H, timeout=10)
print(json.dumps(r.json(), indent=2))
