import unittest
from unittest.mock import MagicMock, patch
from services.adapters import LetterGenAdapter
from utils.hf_parser import parse_letter_generator_output

class TestLetterGenFlow(unittest.TestCase):

    @patch('services.adapters.GradioClient')
    def test_start_session(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_client.session_hash = "mock-session-id"
        mock_gradio_client.return_value = mock_client
        
        # /detect_letter returns a 7-element tuple:
        mock_client.predict.return_value = (
            "<p>Letter type:</b> Leave Letter</p><p>Confidence:</b> 98%</p>",
            "<b>1. Reason</b><br><b>2. Days</b>",
            '{"type": "Leave Letter"}',
            "Reason for leave?",
            "",
            "1/2",
            "asking"
        )

        adapter = LetterGenAdapter("DeffoTech/Letter_Generation", "mock-token")
        res = adapter.run("I need a school leave letter")
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "start")
        self.assertEqual(res["session_id"], "mock-session-id")

        # Parse the adapter result
        parsed = parse_letter_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["step"], "ask_question")
        self.assertEqual(parsed["session_id"], "mock-session-id")
        self.assertEqual(parsed["type"], "Leave Letter")
        self.assertEqual(parsed["confidence"], "98%")
        self.assertEqual(parsed["questions"], ["Reason", "Days"])
        self.assertEqual(parsed["current_question"], "Reason for leave?")
        self.assertEqual(parsed["progress"], "1/2")
        self.assertEqual(parsed["answers_json"], '{"type": "Leave Letter"}')

    @patch('services.adapters.GradioClient')
    def test_next_question_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /next_question returns a 5-element tuple
        mock_client.predict.return_value = (
            "How many days?",
            "",
            "2/2",
            '{"type": "Leave Letter", "reason": "Sick"}',
            "asking"
        )

        adapter = LetterGenAdapter("DeffoTech/Letter_Generation", "mock-token")
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "next",
            "answer": "Sick"
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "next")
        self.assertEqual(res["session_id"], "mock-session-id")

        # Parse the result
        parsed = parse_letter_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["step"], "ask_question")
        self.assertEqual(parsed["current_question"], "How many days?")
        self.assertEqual(parsed["progress"], "2/2")
        self.assertEqual(parsed["answers_json"], '{"type": "Leave Letter", "reason": "Sick"}')

        mock_client.predict.assert_called_with("Sick", api_name="/next_question")

    @patch('services.adapters.GradioClient')
    def test_prev_question_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /prev_question returns a 3-element tuple
        mock_client.predict.return_value = (
            "Reason for leave?",
            "",
            "1/2"
        )

        adapter = LetterGenAdapter("DeffoTech/Letter_Generation", "mock-token")
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "prev"
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "prev")
        
        parsed = parse_letter_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["current_question"], "Reason for leave?")
        self.assertEqual(parsed["progress"], "1/2")

        mock_client.predict.assert_called_with(api_name="/prev_question")

    @patch('services.adapters.GradioClient')
    def test_generate_letter_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /generate_letter returns the letter string
        mock_client.predict.return_value = "Tamil Letter Content Here"

        adapter = LetterGenAdapter("DeffoTech/Letter_Generation", "mock-token")
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "generate",
            "user_request": "I need a school leave letter",
            "answers_json": '{"type": "Leave Letter", "reason": "Sick", "days": "2"}',
            "template_index": 1
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "generate")
        self.assertEqual(res["raw_data"], "Tamil Letter Content Here")

        # Parse the result
        parsed = parse_letter_generator_output(res)
        self.assertEqual(parsed["status"], "done")
        self.assertEqual(parsed["step"], "generate")
        self.assertEqual(parsed["letter"], "Tamil Letter Content Here")
        
        mock_client.predict.assert_called_with("I need a school leave letter", '{"type": "Leave Letter", "reason": "Sick", "days": "2"}', 1.0, api_name="/generate_letter")

if __name__ == '__main__':
    unittest.main()
