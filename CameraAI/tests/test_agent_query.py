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
        with patch('main.query_vision_agent_text', side_effect=Exception("Server offline")):
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
        with patch('main.query_vision_agent_text', side_effect=Exception("Server offline")):
            with patch('database.get_events', return_value=fake_events):
                response = self.client.post('/api/agent/query', json={'query': 'Kiểm tra cảnh báo bất thường', 'channel': 3})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertIn('Vượt hàng rào', data['reply'])
                self.assertEqual(data['channel'], 3)
                self.assertEqual(len(data['matched_events']), 1)
                self.assertEqual(data['matched_events'][0]['id'], 101)

    def test_quick_analyze_event_returns_grounded_report(self):
        fake_event = {
            'id': 88,
            'event_code': 'Fight',
            'event_type': 'video_anomaly',
            'channel': 5,
            'timestamp': '2026-09-07 08:00:00',
            'description': 'Nghi vấn đánh nhau',
            'severity': 'high',
            'clip_filename': None
        }
        with patch('database.get_event_by_id', return_value=fake_event), \
             patch('database.get_video_analysis', return_value=None), \
             patch('database.get_audio_analysis', return_value=None), \
             patch('database.create_audio_analysis', return_value=True), \
             patch('database.update_audio_analysis', return_value=True), \
             patch('main.generate_final_video_report', return_value=({'summary': 'Chưa đủ chứng cứ bạo lực.', 'risk_level': 'low', 'recommended_action': 'Kiểm tra camera', 'evidence': []}, 'gemini-test')):
            response = self.client.post('/api/events/88/quick-analyze')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['status'], 'completed')
            self.assertEqual(data['event_id'], 88)
            self.assertEqual(data['report']['risk_level'], 'low')
