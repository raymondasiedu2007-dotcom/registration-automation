"""
Test and demo script for concurrent AI form field mapping.

This script demonstrates how to use the concurrent mode where both
Kimi (Moonshot) and Qwen (Alibaba) models analyze form fields
simultaneously and merge their results.
"""

import asyncio
from app.ai_mapper import AIFormMapper
from app.models import FieldMetadata


async def demo_single_model_mode():
    """Demonstrate single model mode (legacy)."""
    config = {
        "enabled": True,
        "concurrent": False,
        "provider": "openai-compatible",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key": "your-kimi-api-key-here",
        "model": "kimi-k2",
        "confidence_threshold": 0.8,
    }
    
    mapper = AIFormMapper(config)
    
    # Create sample form fields
    fields = [
        FieldMetadata(selector="#email", tag="input", input_type="email", label="Email Address"),
        FieldMetadata(selector="#firstName", tag="input", input_type="text", label="First Name"),
        FieldMetadata(selector="#lastName", tag="input", input_type="text", label="Last Name"),
    ]
    
    try:
        # Single model call
        mappings = await mapper.map_fields(fields)
        print("Single Model Mode Results:")
        print(mappings)
    except Exception as e:
        print(f"Error: {e}")


async def demo_concurrent_mode():
    """Demonstrate concurrent mode with both Kimi and Qwen."""
    config = {
        "enabled": True,
        "concurrent": True,  # Enable concurrent mode
        "merge_strategy": "average",  # Options: "average" (default), "highest", "consensus"
        
        # Kimi (Moonshot) configuration
        "kimi": {
            "base_url": "https://api.moonshot.ai/v1",
            "api_key": "your-kimi-api-key",
            "model": "kimi-k2",
        },
        
        # Qwen (Alibaba) configuration
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "your-qwen-api-key",
            "model": "qwen-plus",
        },
        
        "confidence_threshold": 0.8,
    }
    
    mapper = AIFormMapper(config)
    
    # Create sample form fields
    fields = [
        FieldMetadata(selector="#email", tag="input", input_type="email", label="Email Address"),
        FieldMetadata(selector="#firstName", tag="input", input_type="text", label="First Name"),
        FieldMetadata(selector="#lastName", tag="input", input_type="text", label="Last Name"),
        FieldMetadata(selector="#address", tag="input", input_type="text", label="Street Address"),
        FieldMetadata(selector="#phone", tag="input", input_type="tel", label="Phone Number"),
    ]
    
    try:
        # Both models run concurrently and results are merged
        mappings = await mapper.map_fields(fields)
        print("\nConcurrent Mode Results (Kimi + Qwen):")
        print("Merge Strategy: average")
        print(mappings)
        
        # Results explanation:
        # - Both models analyze the form fields simultaneously
        # - Each model returns confidence scores for field mappings
        # - Results are merged using the selected strategy:
        #   * "average": Takes the page field with highest average confidence
        #   * "highest": Takes the field with highest confidence among all votes
        #   * "consensus": Only accepts if both models agree on same field
        
    except Exception as e:
        print(f"Error: {e}")


async def demo_merge_strategies():
    """Show difference between merge strategies."""
    print("\n" + "="*60)
    print("MERGE STRATEGIES EXPLANATION")
    print("="*60)
    
    print("""
1. AVERAGE (default):
   - Averages confidence scores across both models
   - Most balanced approach
   - Example: Both models say "email" with 0.95 → Result: "email" (0.95)
   
2. HIGHEST:
   - Selects field with highest average confidence
   - Conservative approach
   - Example: Kimi says "email" (0.95), Qwen says "email" (0.90) → "email" (0.925)
   
3. CONSENSUS:
   - Only accepts mappings where both models agree
   - Most strict approach
   - Example: Kimi says "email", Qwen says "phone" → No mapping (disagreement)
    """)


async def demo_environment_variables():
    """Show how to configure via environment variables."""
    print("\n" + "="*60)
    print("ENVIRONMENT VARIABLES SETUP")
    print("="*60)
    
    print("""
Create a .env file with:

# Single Model Mode (legacy):
AI_API_KEY=your-key
AI_BASE_URL=https://api.moonshot.ai/v1
AI_MODEL=kimi-k2

# Concurrent Mode:
KIMI_API_KEY=your-kimi-key
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2

QWEN_API_KEY=your-qwen-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

Then in config.yaml:
ai:
  enabled: true
  concurrent: true  # Enable concurrent mode
  merge_strategy: "average"  # or "highest", "consensus"
  kimi:
    api_key: "${KIMI_API_KEY}"
    # ... other kimi config
  qwen:
    api_key: "${QWEN_API_KEY}"
    # ... other qwen config
    """)


async def main():
    """Run all demos."""
    print("="*60)
    print("AI FORM FIELD MAPPER - CONCURRENT MODE DEMO")
    print("="*60)
    
    await demo_environment_variables()
    await demo_merge_strategies()
    
    print("\n" + "="*60)
    print("NOTE: To run the actual examples, configure your API keys:")
    print("1. Get Kimi API key: https://platform.moonshot.ai/")
    print("2. Get Qwen API key: https://dashscope.aliyuncs.com/")
    print("3. Update config.yaml with concurrent: true")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
