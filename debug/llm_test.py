
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.config import load_config, build_llm_from_config
from llm_engine.base import LLMMessage

def test_llm():
    print("--- AIRPG LLM Parameter Test ---")
    config = load_config()
    print(f"Backend: {config.llm_backend}")
    
    if config.llm_backend == "universal":
        print(f"URL: {config.universal_base_url}")
        print(f"Model: {config.universal_model}")
    elif config.llm_backend == "gemini":
        print(f"Model: {config.gemini_model}")

    try:
        llm = build_llm_from_config(config)
        print("Checking availability...")
        if llm.is_available():
            print("Status: [CONNECTED] Backend is reachable.")
            
            # Test different temperatures
            for temp in [0.0, 0.7, 1.0]:
                print(f"\n--- Testing with Temperature: {temp} ---")
                messages: list[LLMMessage] = [{"role": "user", "content": "Tell me a short 3-word story."}]
                
                # Test complete()
                print(f"Calling complete(temperature={temp})...")
                resp = llm.complete(messages, temperature=temp, top_p=1.0)
                print(f"Response: '{resp.narrative_text}'")
                
                # Test stream_tokens()
                print(f"Calling stream_tokens(temperature={temp})...")
                tokens = []
                for token in llm.stream_tokens(messages, temperature=temp, top_p=1.0):
                    tokens.append(token)
                    print(token, end="", flush=True)
                print(f"\nFull Streamed Response: '{''.join(tokens)}'")

            print("\nTest successful.")
        else:
            print("Status: [FAILED] Backend is unreachable. Check your settings or server.")
    except Exception as e:
        print(f"Status: [ERROR] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_llm()
