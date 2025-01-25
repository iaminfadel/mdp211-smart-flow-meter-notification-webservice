from flask import Flask, request, jsonify
from firebase_admin import credentials, db, initialize_app
import firebase_admin
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timezone
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import requests
from enum import Enum
from typing import Dict, Optional


# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Firebase with credentials from environment
cred_dict = json.loads(os.getenv('FIREBASE_CREDENTIALS'))
cred = credentials.Certificate(cred_dict)
initialize_app(cred, {
    'databaseURL': os.getenv('FIREBASE_DATABASE_URL')
})

class WarningType(Enum):
    FLOWRATE = "flowrate"
    TEMPERATURE = "temperature"
    PRESSURE = "pressure"

class SeverityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class FCMNotifier:
    def __init__(self, credentials_dict, project_id):
        """
        Initialize FCM notifier with service account credentials from dictionary
        
        Args:
            credentials_dict (dict): Service account credentials as a dictionary
            project_id (str): Firebase project ID
        """
        self.project_id = project_id
        self.base_url = f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
        
        try:
            # Create credentials object from dictionary
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/firebase.messaging']
            )
            print("Credentials loaded successfully")
        except Exception as e:
            print(f"Error loading credentials: {e}")
            raise

    def get_access_token(self):
        """Get OAuth 2.0 access token"""
        try:
            request = Request()
            self.credentials.refresh(request)
            token = self.credentials.token
            print(f"Access token obtained successfully: {token[:10]}...")
            return token
        except Exception as e:
            print(f"Error getting access token: {e}")
            raise

    def send_notification(self, device_token, title, body, data=None):
        """
        Send FCM notification to a specific device
        """
        try:
            # Get fresh token
            token = self.get_access_token()
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }
            
            # Construct message
            message = {
                'message': {
                    'token': device_token,
                    'notification': {
                        'title': title,
                        'body': body
                    },
                    'android': {
                        'priority':'high',
                        'notification': {
                            'title': title,
                            'body': body,
                            'color':'#ff0000',
                            'sound':'default',
                            'notification_priority': 'PRIORITY_MAX'
                        },
                    }
                }
            }
            
            if data:
                message['message']['data'] = data
            
            print(f"Sending request to: {self.base_url}")
            print(f"Request payload: {json.dumps(message, indent=2)}")
            
            response = requests.post(
                self.base_url,
                headers=headers,
                json=message
            )
            
            print(f"Response status code: {response.status_code}")
            print(f"Response body: {response.text}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Error response: {e.response.text}")
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

# And in your FlowmeterMonitor class initialization:
class FlowmeterMonitor:
    def __init__(self, database_url: str, credentials_dict: dict, project_id: str):
        # Initialize Firebase
        if not firebase_admin._apps:  # Only initialize if not already initialized
            cred = credentials.Certificate(credentials_dict)
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })
        self.db = db.reference()
        
        # Initialize FCM client with credentials dictionary
        self.fcm_client = FCMNotifier(credentials_dict, project_id)

    def update_readings(self, serial_number: str, flowrate: Optional[float] = None,
                       temperature: Optional[float] = None, pressure: Optional[float] = None,
                          humidity: Optional[float] = None):
        """Update flowmeter readings and check for warnings"""
        
        # Get flowmeter reference
        flowmeter_ref = self.db.child('flowmeters').order_by_child('serialNumber').equal_to(serial_number).get()
        if not flowmeter_ref:
            raise ValueError("Flowmeter not found")
        
        flowmeter_id = list(flowmeter_ref.keys())[0]
        readings_ref = self.db.child('flowmeters').child(flowmeter_id).child('currentReadings')
        
        # Update readings
        updates = {}
        if flowrate is not None:
            updates['flowrate'] = flowrate
        if temperature is not None:
            updates['temperature'] = temperature
        if pressure is not None:
            updates['pressure'] = pressure
        if humidity is not None:
            updates['humidity'] = humidity
        
        updates['lastUpdated'] = datetime.now(timezone.utc).isoformat()
        readings_ref.update(updates)

        # Add to historical readings
        historical_ref = self.db.child('flowmeters').child(flowmeter_id).child('logs').push(updates)
        
        # Get associated users
        users_ref = self.db.child('flowmeters').child(flowmeter_id).child('users').get()
        if users_ref:
            for user_id in users_ref.keys():
                self._check_thresholds(user_id, flowmeter_id, updates)

    def _check_thresholds(self, user_id: str, flowmeter_id: str, readings: Dict[str, float]):
        """Check all thresholds for a user"""
        thresholds = self.db.child('users').child(user_id).child('flowmeters') \
                        .child(flowmeter_id).child('thresholds').get()
        
        if not thresholds:
            return
            
        for reading_type in [WarningType.FLOWRATE, WarningType.TEMPERATURE, WarningType.PRESSURE]:
            if reading_type.value in readings and reading_type.value in thresholds:
                value = readings[reading_type.value]
                type_thresholds = thresholds[reading_type.value]
                
                self._check_single_threshold(
                    user_id, flowmeter_id, reading_type, value, type_thresholds
                )

    def _check_single_threshold(self, user_id: str, flowmeter_id: str, 
                              warning_type: WarningType, value: float, 
                              thresholds: Dict[str, float]):
        """Check a single reading against its thresholds"""
        # Check thresholds from highest to lowest
        severity_order = {
            'high': 3,
            'medium': 2,
            'low': 1
        }
        
        triggered_severity = None
        triggered_threshold = None
        
        # for severity, threshold in sorted(thresholds.items(), 
        #                                key=lambda x: severity_order.get(x[0], 0),
        #                                reverse=True):
        #     if value > threshold:
        #         triggered_severity = severity
        #         triggered_threshold = threshold
        #         break
        if value > thresholds['high'] and thresholds['high'] != 0:
            triggered_severity = 'high'
            triggered_threshold = thresholds['high']
        elif value < thresholds['low'] and thresholds['low'] != 0:
            triggered_severity = 'low'
            triggered_threshold = thresholds['low']

        if triggered_severity:
            # Create warning
            warning_data = {
                'userId': user_id,
                'type': warning_type.value,
                'severity': triggered_severity,
                'reading': value,
                'threshold': triggered_threshold,
                'timestamp': datetime.utcnow().isoformat(),
                'acknowledged': False,
                'acknowledgedAt': None
            }
            
            # Add warning to database
            warning_ref = self.db.child('warnings').child(flowmeter_id).push(warning_data)
            warning_id = warning_ref.key
            
            # Add to user warnings index
            self.db.child('userWarnings').child(user_id).child(warning_id).set(True)
            
            # Send notifications
            self._send_warning_notification(
                user_id, flowmeter_id, warning_type, 
                triggered_severity, value, triggered_threshold
            )

    def _send_warning_notification(self, user_id: str, flowmeter_id: str,
                                 warning_type: WarningType, severity: str,
                                 value: float, threshold: float):
        """Send warning notifications to all user devices"""
        devices = self.db.child('users').child(user_id).child('devices').get()
        flowmeter = self.db.child('flowmeters').child(flowmeter_id).get()
        
        title = f"{severity.upper()} {warning_type.value.title()} Alert"
        body = (f"Flowmeter {flowmeter['serialNumber']} {warning_type.value} "
               f"exceeded {severity} threshold: {value:.2f} > {threshold:.2f}")
        
        if devices:
            for device_id, device_data in devices.items():
                if device_data.get('notificationsEnabled', True):
                    try:
                        self.fcm_client.send_notification(
                            device_token=device_data['fcmToken'],
                            title=title,
                            body=body,
                            data={
                                'type': 'threshold_warning',
                                'warning_type': warning_type.value,
                                'severity': severity,
                                'flowmeter_id': flowmeter_id,
                                'reading': str(value),
                                'threshold': str(threshold),
                                'timestamp': datetime.utcnow().isoformat()
                            }
                        )
                    except Exception as e:
                        print(f"Failed to send notification to device {device_id}: {e}")

    def acknowledge_warning(self, warning_id: str, flowmeter_id: str, user_id: str):
        """Acknowledge a warning"""
        warning_ref = self.db.child('warnings').child(flowmeter_id).child(warning_id)
        warning = warning_ref.get()
        
        if not warning:
            raise ValueError("Warning not found")
            
        if warning['userId'] != user_id:
            raise ValueError("User does not have permission to acknowledge this warning")
            
        warning_ref.update({
            'acknowledged': True,
            'acknowledgedAt': datetime.utcnow().isoformat()
        })


cred_dict = json.loads(os.getenv('FIREBASE_CREDENTIALS'))

# Initialize monitor with credentials dictionary
monitor = FlowmeterMonitor(
    database_url=os.getenv('FIREBASE_DATABASE_URL'),
    credentials_dict=cred_dict,
    project_id=os.getenv('FIREBASE_PROJECT_ID')
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
            pressure=data.get('pressure'),
            humidity=data.get('humidity')
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