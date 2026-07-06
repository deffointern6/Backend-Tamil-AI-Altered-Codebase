import unittest
from unittest.mock import patch, MagicMock
from services.adapters import MCQGenAdapter
from utils.hf_parser import parse_model_output

class TestMCQGenFlow(unittest.TestCase):

    @patch('services.adapters.GradioClient')
    def test_mcq_gen_success(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_client.predict.return_value = [
            "✅ Successfully generated 1 MCQs!",
            [
                {
                    "question": "தமிழ்நாட்டின் தலைநகரம் எது?",
                    "options": ["சென்னை", "மதுரை", "கோவை", "திருச்சி"],
                    "answer": "சென்னை"
                }
            ]
        ]
        mock_gradio_client.return_value = mock_client

        adapter = MCQGenAdapter("DeffoTech/MCQ_generator", "mock-token")
        res = adapter.run("தமிழ்நாட்டின் தலைநகரம் சென்னை ஆகும்.")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source"], "hf-space")
        self.assertEqual(res["model"], "DeffoTech/MCQ_generator")
        
        # Verify parser
        parsed = parse_model_output("mcq-gen", res)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["answer"], "சென்னை")

    @patch('services.adapters.GradioClient')
    def test_mcq_gen_no_sentences_warning(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_client.predict.return_value = "ℹ️ No suitable sentences found for MCQ generation. Try a longer, more descriptive paragraph."
        mock_gradio_client.return_value = mock_client

        adapter = MCQGenAdapter("DeffoTech/MCQ_generator", "mock-token")
        with self.assertRaises(RuntimeError) as context:
            adapter.run("வணக்கம்.")
        self.assertIn("No suitable sentences", str(context.exception))

    @patch('services.adapters.GradioClient')
    def test_mcq_gen_http_error(self, mock_gradio_client):
        mock_client = MagicMock()
        mock_client.predict.side_effect = Exception("Connection timed out")
        mock_gradio_client.return_value = mock_client

        adapter = MCQGenAdapter("DeffoTech/MCQ_generator", "mock-token")
        with self.assertRaises(RuntimeError) as context:
            adapter.run("தமிழ்நாட்டின் தலைநகரம் சென்னை ஆகும்.")
        self.assertIn("Connection timed out", str(context.exception))

    def test_mcq_gen_empty_input(self):
        adapter = MCQGenAdapter("DeffoTech/MCQ_generator", "mock-token")
        with self.assertRaises(ValueError):
            adapter.run("")

    def test_parser_validation(self):
        # Test parser error case for non-list data
        err_res = parse_model_output("mcq-gen", {"status": "success", "data": "invalid_not_a_list"})
        self.assertIn("error", err_res)
        self.assertEqual(err_res["error"], "Invalid MCQ response format: expected a list of questions.")

        # Test parser error case for empty list
        empty_res = parse_model_output("mcq-gen", {"status": "success", "data": []})
        self.assertIn("error", empty_res)
        self.assertEqual(empty_res["error"], "No MCQs were generated. Try a longer, more descriptive passage.")

if __name__ == '__main__':
    unittest.main()
