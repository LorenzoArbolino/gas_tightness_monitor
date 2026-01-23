"""
Debug script to test AGSI API connection
"""
import requests
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import GIE_API_KEY, AGSI_BASE_URL


def test_agsi_api():
    """Test different AGSI API endpoints"""
    
    print("=== Testing AGSI API ===\n")
    print(f"Base URL: {AGSI_BASE_URL}")
    print(f"API Key (last 4): ...{GIE_API_KEY[-4:]}\n")
    
    headers = {
        'x-key': GIE_API_KEY,
        'Accept': 'application/json'
    }
    
    # Test different endpoint variations
    endpoints_to_test = [
        "/EU",
        "/data/EU",
        "?country=EU",
    ]
    
    for endpoint in endpoints_to_test:
        url = f"{AGSI_BASE_URL}{endpoint}"
        print(f"\n--- Testing: {url} ---")
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Success!")
                print(f"Response type: {type(data)}")
                
                if isinstance(data, dict):
                    print(f"Keys: {list(data.keys())}")
                    if 'data' in data:
                        print(f"Data records: {len(data['data'])}")
                        if len(data['data']) > 0:
                            print(f"First record keys: {list(data['data'][0].keys())}")
                            print(f"Sample record:")
                            print(json.dumps(data['data'][0], indent=2))
                elif isinstance(data, list):
                    print(f"List length: {len(data)}")
                    if len(data) > 0:
                        print(f"First record keys: {list(data[0].keys())}")
                        print(f"Sample record:")
                        print(json.dumps(data[0], indent=2))
                
                # This endpoint works - stop here
                print("\n✓✓✓ THIS ENDPOINT WORKS! ✓✓✓")
                return url, data
                
            else:
                print(f"✗ Failed: {response.text[:200]}")
                
        except Exception as e:
            print(f"✗ Error: {e}")
    
    print("\n⚠ No working endpoint found!")
    return None, None


def test_with_params():
    """Test API with date parameters"""
    
    print("\n\n=== Testing with Date Parameters ===\n")
    
    headers = {
        'x-key': GIE_API_KEY,
        'Accept': 'application/json'
    }
    
    # Test recent data
    url = f"{AGSI_BASE_URL}/EU"
    params = {
        'from': '2026-01-01',
        'to': '2026-01-20'
    }
    
    print(f"URL: {url}")
    print(f"Params: {params}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Success!")
            
            if isinstance(data, dict) and 'data' in data:
                print(f"Records returned: {len(data['data'])}")
            elif isinstance(data, list):
                print(f"Records returned: {len(data)}")
                
        else:
            print(f"✗ Failed: {response.text[:200]}")
            
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    working_url, sample_data = test_agsi_api()
    
    if working_url:
        test_with_params()
    
    print("\n=== Test Complete ===")
