import json
from client import search_local_index

def test_search():
    print("--- Running client local search verification ---")
    
    # Mock chart data
    chart_data = {
        "ascendant": {
            "sign": "Virgo"
        },
        "planets": {
            "Sun": {
                "sign": "Sagittarius",
                "house": 4
            },
            "Saturn": {
                "sign": "Virgo",
                "house": 1
            }
        },
        "upagrahas": {
            "Gulika": {
                "sign": "Leo",
                "house": 12
            }
        }
    }
    
    results = search_local_index(chart_data)
    print("Retrieved search matches snippet:")
    print(results[:1000] + "\n...")
    
    # Assertions
    assert "Book:" in results, "No book results found!"
    assert "Page" in results, "No page numbers found in results!"
    assert "--- Match 1 |" in results, "First match is missing!"
    assert "--- Match 3 |" not in results, "Returned more than 2 matches!"
    print("\nSUCCESS: Client local search successfully queried indexed_knowledge.json with a strict limit of 2 matches!")

if __name__ == "__main__":
    test_search()
