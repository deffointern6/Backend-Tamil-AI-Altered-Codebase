import unittest
from unittest.mock import MagicMock, patch
from services.adapters import EmailGenAdapter
from utils.hf_parser import parse_email_generator_output

class TestEmailGenFlow(unittest.TestCase):

    @patch('services.adapters.GradioClient')
    def test_start_session(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_client.session_hash = "mock-session-id"
        mock_gradio_client.return_value = mock_client
        
        # /detect_email returns a 7-element tuple
        mock_client.predict.return_value = (
            "<p>Email type:</b> Professional Email</p>",
            "<p>Confidence:</b> 95%</p>",
            '{"type": "Professional Email"}',
            "What is the recipient's name?",
            "",
            "1/3",
            "asking"
        )

        adapter = EmailGenAdapter("DeffoTech/Tamil_Email_Generation", "mock-token")
        res = adapter.run("சம்பளச் சீட்டு வழங்குமாறு மனிதவளத்துறைக்கு மின்னஞ்சல் அனுப்ப வேண்டும்")
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "start")
        self.assertEqual(res["session_id"], "mock-session-id")

        # Parse the adapter result
        parsed = parse_email_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["step"], "ask_question")
        self.assertEqual(parsed["session_id"], "mock-session-id")
        self.assertEqual(parsed["type"], "Professional Email")
        self.assertEqual(parsed["confidence"], "95%")
        self.assertEqual(parsed["current_question"], "What is the recipient's name?")
        self.assertEqual(parsed["progress"], "1/3")
        self.assertEqual(parsed["answers_json"], '{"type": "Professional Email"}')

    @patch('services.adapters.GradioClient')
    def test_next_question_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /next_question returns a 5-element tuple
        mock_client.predict.return_value = (
            "What is the subject of the email?",
            "",
            "2/3",
            '{"type": "Professional Email", "recipient": "HR"}',
            "asking"
        )

        adapter = EmailGenAdapter("DeffoTech/Tamil_Email_Generation", "mock-token")
        
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "next",
            "answer": "HR"
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "next")
        self.assertEqual(res["session_id"], "mock-session-id")

        # Parse the result
        parsed = parse_email_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["step"], "ask_question")
        self.assertEqual(parsed["current_question"], "What is the subject of the email?")
        self.assertEqual(parsed["progress"], "2/3")
        self.assertEqual(parsed["answers_json"], '{"type": "Professional Email", "recipient": "HR"}')

        mock_client.predict.assert_called_with("HR", api_name="/next_question")

    @patch('services.adapters.GradioClient')
    def test_prev_question_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /prev_question returns a 3-element tuple
        mock_client.predict.return_value = (
            "What is the recipient's name?",
            "",
            "1/3"
        )

        adapter = EmailGenAdapter("DeffoTech/Tamil_Email_Generation", "mock-token")
        
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "prev"
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "prev")
        self.assertEqual(res["session_id"], "mock-session-id")
        
        parsed = parse_email_generator_output(res)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["current_question"], "What is the recipient's name?")
        self.assertEqual(parsed["progress"], "1/3")

        mock_client.predict.assert_called_with(api_name="/prev_question")

    @patch('services.adapters.GradioClient')
    def test_generate_email_flow(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_gradio_client.return_value = mock_client
        
        # /generate_email returns the email string
        mock_client.predict.return_value = "Tamil Email Content Here"

        adapter = EmailGenAdapter("DeffoTech/Tamil_Email_Generation", "mock-token")
        
        res = adapter.run({
            "session_id": "mock-session-id",
            "action": "generate",
            "answers_json": '{"type": "Professional Email", "recipient": "HR", "subject": "Salary slip"}'
        })
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["step"], "generate")
        self.assertEqual(res["raw_data"], "Tamil Email Content Here")

        # Parse the result
        parsed = parse_email_generator_output(res)
        self.assertEqual(parsed["status"], "done")
        self.assertEqual(parsed["step"], "generate")
        self.assertEqual(parsed["email"], "Tamil Email Content Here")
        
        mock_client.predict.assert_called_with('{"type": "Professional Email", "recipient": "HR", "subject": "Salary slip"}', api_name="/generate_email")

if __name__ == '__main__':
    unittest.main()
