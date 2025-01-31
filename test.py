import requests
import json

jsonData='{"serial_number": "99", "flowrate": 50.0, "temperature": 25, "pressure": 50, "rpm": 100}'
# Update readings
response = requests.post(
    'https://mdp211-smart-flow-meter-notification.onrender.com/update-readings',
    json=json.loads(jsonData)
)
print(response.json())

# # Acknowledge warning
# response = requests.post(
#     'https://mdp211-smart-flow-meter-notification.onrender.com',
#     json={
#         'warning_id': 'warning123',
#         'flowmeter_id': 'flowmeter123',
#         'user_id': 'user123'
#     }
# )
# print(response.json())