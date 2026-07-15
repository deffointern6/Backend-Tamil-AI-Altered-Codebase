import os
import sys
import shutil

# Ensure the project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from huggingface_hub import snapshot_download
from settings.config import settings

LIVE_TEXT_SPACES = {
    "letter-gen": "DeffoTech/Letter_Generation",
    "paraphrase-gen": "DeffoTech/Tamil-Paraphrase-AI",
    "mcq-gen": "DeffoTech/MCQ_generator",
    "tongue-twister": "DeffoTech/Tamil-Tongue-Twister_final",
    "poem-gen": "DeffoTech/Tamil-Poem-Generator-V6",
    "email-gen": "DeffoTech/Tamil_Email_Generation",
    "proofreader": "hxari/tamil-spell-checker"
}

def main():
    token = getattr(settings, "hf_token", "")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = os.path.join(project_root, "local_spaces")
    os.makedirs(base_dir, exist_ok=True)
    
    for name, repo_id in LIVE_TEXT_SPACES.items():
        print(f"Downloading Space '{repo_id}' for '{name}'...")
        target_dir = os.path.join(base_dir, name)
        
        if os.path.exists(target_dir):
            print(f"Cleaning up existing directory: {target_dir}")
            shutil.rmtree(target_dir)
            
        try:
            snapshot_download(
                repo_id=repo_id,
                repo_type="space",
                local_dir=target_dir,
                token=token,
                ignore_patterns=["*.git*"]
            )
            print(f"Successfully downloaded to {target_dir}\n")
        except Exception as e:
            print(f"Error downloading {repo_id}: {e}\n")

if __name__ == "__main__":
    main()
