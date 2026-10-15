import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app, get_admin_credentials, login_rate_limiter

class AgentQueryTest(unittest.TestCase):
    def setUp(self):
        login_rate_limiter.reset()
        self.client = TestClient(app)
        username, password = get_admin_credentials()
        response = self.client.post(
            '/api/admin/verify-login',
            json={'username': username, 'password': password},
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        login_rate_limiter.reset()
        self.client.close()

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

    def test_agent_query_nightly_report_context_injected_to_qwen(self):
        fake_report = {
            'type': 'single_camera',
            'report_date': '14/10/2026',
            'channel': 18,
            'camera_name': '18.T1. SẢNH CHÍNH',
            'window_start': '13/10/2026 22:00:00',
            'window_end': '14/10/2026 22:00:00',
            'risk_label': 'Bình thường',
            'total_events': 45,
            'anomaly_count': 0,
            'human_count': 30,
            'vehicle_count': 10,
            'clip_count': 5,
            'peak_hour_label': '07:00 - 08:00',
            'executive_summary': 'Khu vực sảnh chính hoạt động ổn định, không có đột nhập.',
            'shifts': [
                {
                    'title': 'Ca 1 (22:00 - 04:00) Trực đêm',
                    'summary_text': 'An toàn tuyệt đối, không phát hiện người lạ',
                    'event_count': 2,
                    'anomaly_count': 0
                }
            ],
            'notable_events': []
        }
        captured_kwargs = {}

        def fake_query_vision_agent_text(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                'reply': 'Theo báo cáo đêm 14/10/2026, khu vực sảnh chính an toàn tuyệt đối.',
                'reasoning': 'Dựa trên báo cáo đêm ca 1.',
                'source': 'Vision Agent Test'
            }

        with patch('main.get_nightly_report_for_ai', return_value=fake_report),              patch('main.query_vision_agent_text', side_effect=fake_query_vision_agent_text),              patch('database.get_events', return_value=[]):
            response = self.client.post('/api/agent/query', json={
                'query': 'Tình hình báo cáo ca trực đêm qua thế nào?',
                'channel': 18
            })
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('sảnh chính an toàn tuyệt đối', data['reply'])
            context_str = '\n'.join(captured_kwargs.get('context_lines', []))
            self.assertIn('THÔNG TIN BÁO CÁO CA TRỰC & AN NINH ĐÊM CHÍNH THỨC', context_str)
            self.assertIn('18.T1. SẢNH CHÍNH', context_str)
            self.assertIn('Ca 1 (22:00 - 04:00) Trực đêm', context_str)

    def test_agent_query_nightly_report_fallback(self):
        fake_report = {
            'type': 'master_summary',
            'report_date': '14/10/2026',
            'window_start': '13/10/2026 22:00:00',
            'window_end': '14/10/2026 22:00:00',
            'total_cameras': 32,
            'active_cameras': 2,
            'total_events': 120,
            'total_anomalies': 0,
            'active_cameras_detail': [],
            'all_cameras_summary': []
        }
        with patch('main.get_nightly_report_for_ai', return_value=fake_report),              patch('main.query_vision_agent_text', side_effect=Exception('Qwen server offline')),              patch('database.get_events', return_value=[]):
            response = self.client.post('/api/agent/query', json={
                'query': 'Báo cáo đêm toàn hệ thống',
                'channel': None
            })
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('Báo cáo đêm tổng hợp toàn trường (14/10/2026)', data['reply'])
            self.assertIn('32 camera', data['reply'])
