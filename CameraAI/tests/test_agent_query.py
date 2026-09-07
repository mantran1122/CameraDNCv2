import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app

class AgentQueryTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_agent_query_empty_text_returns_greeting(self):
        response = self.client.post('/api/agent/query', json={'query': '', 'channel': 2})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('Xin chào', data['reply'])
        self.assertEqual(data['channel'], 2)

    def test_agent_query_anomaly_keyword_without_events(self):
        with patch('database.get_events', return_value=[]):
            response = self.client.post('/api/agent/query', json={'query': 'Có bất thường không?', 'channel': 1})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('an toàn', data['reply'].lower())

    def test_agent_query_anomaly_keyword_with_events(self):
        fake_events = [{
            'id': 101,
            'event_code': 'CrossFence',
            'event_type': 'video_anomaly',
            'channel': 3,
            'timestamp': '2026-09-07 07:30:00',
            'description': 'Vượt hàng rào bảo vệ',
            'severity': 'high'
        }]
        with patch('database.get_events', return_value=fake_events):
            response = self.client.post('/api/agent/query', json={'query': 'Kiểm tra cảnh báo bất thường', 'channel': 3})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('Vượt hàng rào', data['reply'])
            self.assertEqual(data['channel'], 3)
