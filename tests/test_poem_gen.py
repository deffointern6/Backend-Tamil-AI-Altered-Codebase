import unittest
from utils.hf_parser import parse_poem_generator_output, parse_model_output

class TestPoemGenParser(unittest.TestCase):

    def test_clean_poem_with_trailing_few_shots(self):
        # A mocked response representing the exact raw output with multiple XML-style poem blocks
        raw_output = """மகிழ்ச்சி எனும் வற்றாத ஊற்றாய்
என் நெஞ்சில் நீ நனையும் போது
வாழ்வின் வசந்தம் மீண்டும் பிறந்ததாக உணர்கிறேன்
மகிழ்ச்சியின் ஊற்றாய் நீ மலரும் அந்தத் தருணம்
என் வாழ்வின் பொற்காலத்தை மகுடமாய் எழுதுகிறேன்
</poem>
<poem>
<topic> மழை தரும் தாகம்
<theme> மகிழ்ச்சி
<style> புதுக்கவிதை
குதூகலத்தோடு நான் மழையில் நனைந்து மகிழ்கிறேன்
</poem>"""

        # Verify parser extracts only the first poem block and strips the closing tag
        cleaned = parse_poem_generator_output(raw_output)
        expected = """மகிழ்ச்சி எனும் வற்றாத ஊற்றாய்
என் நெஞ்சில் நீ நனையும் போது
வாழ்வின் வசந்தம் மீண்டும் பிறந்ததாக உணர்கிறேன்
மகிழ்ச்சியின் ஊற்றாய் நீ மலரும் அந்தத் தருணம்
என் வாழ்வின் பொற்காலத்தை மகுடமாய் எழுதுகிறேன்"""
        self.assertEqual(cleaned, expected)

    def test_clean_poem_with_leading_tags(self):
        # Mocked response where the generated text starts with tags
        raw_output = """<poem>
<topic> பருவமழை
<theme> இயற்கை
<style> புதுக்கவிதை
மழை பெய்யும் அழகிய மாலை நேரம்
பூக்கள் எல்லாம் புன்னகைக்கும் காலம்
</poem>"""

        cleaned = parse_poem_generator_output(raw_output)
        expected = """மழை பெய்யும் அழகிய மாலை நேரம்
பூக்கள் எல்லாம் புன்னகைக்கும் காலம்"""
        self.assertEqual(cleaned, expected)

    def test_clean_poem_no_tags(self):
        # When the model already returns clean text
        raw_output = "மழை பெய்யும் அழகிய மாலை நேரம்"
        cleaned = parse_poem_generator_output(raw_output)
        self.assertEqual(cleaned, raw_output)

    def test_centralized_dispatcher(self):
        # Test calling via centralized parse_model_output dispatcher
        res = parse_model_output("poem-gen", {"status": "success", "data": "<poem>மழை</poem>"})
        self.assertEqual(res, "மழை")

if __name__ == '__main__':
    unittest.main()
