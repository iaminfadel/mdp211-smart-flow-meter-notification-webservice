from flask import Flask, request, jsonify
from firebase_admin import credentials, db, initialize_app
import firebase_admin
import os
from dotenv import load_dotenv
import json
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Firebase with credentials from environment
cred_dict = json.loads(os.getenv('FIREBASE_CREDENTIALS'))
cred = credentials.Certificate(cred_dict)
initialize_app(cred, {
    'databaseURL': os.getenv('FIREBASE_DATABASE_URL')
})

class FlowmeterMonitor:
    # Your existing FlowmeterMonitor class code here
    # (The code from the previous example)
    pass

monitor = FlowmeterMonitor(
    service_account_path=None,  # We're using environment variables instead
    database_url=os.getenv('FIREBASE_DATABASE_URL'),
    fcm_project_id=os.getenv('FIREBASE_PROJECT_ID')
)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'}), 200

@app.route('/update-readings', methods=['POST'])
def update_readings():
    try:
        data = request.get_json()
        required_fields = ['serial_number']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Update readings
        monitor.update_readings(
            serial_number=data['serial_number'],
            flowrate=data.get('flowrate'),
            temperature=data.get('temperature'),
            pressure=data.get('pressure')
        )
        
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/acknowledge-warning', methods=['POST'])
def acknowledge_warning():
    try:
        data = request.get_json()
        required_fields = ['warning_id', 'flowmeter_id', 'user_id']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        monitor.acknowledge_warning(
            warning_id=data['warning_id'],
            flowmeter_id=data['flowmeter_id'],
            user_id=data['user_id']
        )
        
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))