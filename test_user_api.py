#!/usr/bin/env python3
"""
Test script for user API endpoints
Run this to verify the backend user management is working correctly
"""

import asyncio
import aiohttp
import json

BACKEND_API_URL = "https://moviebot.click"

async def test_user_api():
    """Test the user API endpoints"""
    
    # Test data
    test_user = {
        "telegram_id": 123456789,
        "first_name": "Test",
        "last_name": "User",
        "preferred_language": "en"
    }
    
    async with aiohttp.ClientSession() as session:
        print("🧪 Testing User API endpoints...")
        
        # Test 1: Create/Get user
        print("\n1. Testing GET/CREATE user...")
        async with session.post(f"{BACKEND_API_URL}/users/get-or-create", json=test_user) as resp:
            if resp.status == 200:
                user_data = await resp.json()
                print(f"✅ User created/retrieved: {user_data}")
            else:
                print(f"❌ Failed to create/get user: {resp.status}")
                return
        
        # Test 2: Get user by ID
        print("\n2. Testing GET user by ID...")
        async with session.get(f"{BACKEND_API_URL}/users/{test_user['telegram_id']}") as resp:
            if resp.status == 200:
                user_data = await resp.json()
                print(f"✅ User retrieved: {user_data}")
            else:
                print(f"❌ Failed to get user: {resp.status}")
        
        # Test 3: Update onboarding
        print("\n3. Testing UPDATE onboarding...")
        onboarding_data = {
            "telegram_id": test_user["telegram_id"],
            "custom_name": "TestCustomName",
            "preferred_language": "ua"
        }
        async with session.post(f"{BACKEND_API_URL}/users/onboarding", json=onboarding_data) as resp:
            if resp.status == 200:
                user_data = await resp.json()
                print(f"✅ Onboarding updated: {user_data}")
            else:
                print(f"❌ Failed to update onboarding: {resp.status}")
        
        # Test 4: Update language
        print("\n4. Testing UPDATE language...")
        language_data = {
            "telegram_id": test_user["telegram_id"],
            "preferred_language": "ru"
        }
        async with session.put(f"{BACKEND_API_URL}/users/language", json=language_data) as resp:
            if resp.status == 200:
                user_data = await resp.json()
                print(f"✅ Language updated: {user_data}")
            else:
                print(f"❌ Failed to update language: {resp.status}")
        
        # Test 5: Final user state
        print("\n5. Testing final user state...")
        async with session.get(f"{BACKEND_API_URL}/users/{test_user['telegram_id']}") as resp:
            if resp.status == 200:
                user_data = await resp.json()
                print(f"✅ Final user state: {user_data}")
            else:
                print(f"❌ Failed to get final user state: {resp.status}")
        
        print("\n🎉 User API tests completed!")

if __name__ == "__main__":
    asyncio.run(test_user_api()) 