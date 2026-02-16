#!/usr/bin/env python3
"""
Wrapper для Sen-Gateway з мультирегіональною підтримкою
Запускай замість run.py
"""
import os
import sys

# Патч для автоматичного вибору регіону
ORIGINAL_AWS_REGION = os.environ.get('AWS_REGION_NAME', 'eu-west-2')

MODEL_REGIONS = {
    'anthropic.claude-sonnet-4-5-20250929-v1:0': 'us-east-1',
    'anthropic.claude-3-sonnet-20240229-v1:0': 'eu-west-2',
    'anthropic.claude-3-7-sonnet-20250219-v1:0': 'eu-west-2',
    'anthropic.claude-haiku-4-5-20251001-v1:0': 'eu-west-2',
    'anthropic.claude-opus-4-5-20251101-v1:0': 'eu-west-2',
}

# Патчимо litellm.completion
import litellm
_original_completion = litellm.completion

def patched_completion(*args, **kwargs):
    """Автоматично встановлює правильний регіон для моделі"""
    model = kwargs.get('model', '')
    
    # Видаляємо bedrock/ префікс для перевірки
    clean_model = model.replace('bedrock/', '')
    
    # Визначаємо регіон
    if clean_model in MODEL_REGIONS:
        region = MODEL_REGIONS[clean_model]
        os.environ['AWS_REGION_NAME'] = region
        print(f"🌍 Auto-region: {model} → {region}")
    
    return _original_completion(*args, **kwargs)

# Застосовуємо патч
litellm.completion = patched_completion

print("=" * 60)
print("🔧 Sen-Gateway Multi-Region Wrapper")
print("=" * 60)
print("📍 Region mapping:")
for model, region in MODEL_REGIONS.items():
    print(f"   {model} → {region}")
print("=" * 60)

# Тепер запускаємо оригінальний Sen-Gateway
if __name__ == "__main__":
    # Імпортуємо основний app
    from app.main import app
    import uvicorn
    
    print("\n🚀 Starting Sen-Gateway with multi-region support...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
