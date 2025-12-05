import os
import json
from typing import List, Dict, Any
from openai import OpenAI
from pydantic import BaseModel

class Match(BaseModel):
    id_a: str
    id_b: str
    confidence: float  # Confidence score from 0.0 to 1.0

class MatchResponse(BaseModel):
    matches: List[Match]

class MarketMatcher:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None
            print("Warning: OPENAI_API_KEY not found. Market matching will be disabled.")

    def match_markets(self, markets_a: List[Dict[str, Any]], markets_b: List[Dict[str, Any]], min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        if not self.client or not markets_a or not markets_b:
            return []

        # 1. Pre-filter candidates using simple string matching to save tokens
        # We only send pairs to the LLM that have some lexical overlap.
        candidates_a = []
        candidates_b = []
        
        # Create a set of significant words for each market in B
        # This is a naive O(N*M) filter but fast enough for 1000x100
        
        def get_tokens(text):
            stop_words = {"will", "the", "to", "be", "in", "on", "at", "by", "a", "of", "for", "is", "it", "this", "that"}
            return set(w.lower() for w in text.split() if w.lower() not in stop_words and w.isalnum())

        map_b_tokens = {m['id']: get_tokens(m['title']) for m in markets_b}
        
        ids_to_send_a = set()
        ids_to_send_b = set()

        for ma in markets_a:
            tokens_a = get_tokens(ma['title'])
            if not tokens_a: continue
            
            for mb in markets_b:
                tokens_b = map_b_tokens[mb['id']]
                if not tokens_b: continue
                
                # Jaccard similarity or simple intersection
                intersection = tokens_a.intersection(tokens_b)
                # If they share at least 2 significant words or 50% overlap
                if len(intersection) >= 2:
                    ids_to_send_a.add(ma['id'])
                    ids_to_send_b.add(mb['id'])

        if not ids_to_send_a or not ids_to_send_b:
            print("No potential matches found after pre-filtering.")
            return []

        print(f"Pre-filtering reduced candidates to {len(ids_to_send_a)} from A and {len(ids_to_send_b)} from B.")

        # Prepare simplified lists for the LLM
        list_a = [{"id": m['id'], "title": m['title']} for m in markets_a if m['id'] in ids_to_send_a]
        list_b = [{"id": m['id'], "title": m['title']} for m in markets_b if m['id'] in ids_to_send_b]

        matched_pairs = []
        map_a = {m['id']: m for m in markets_a}
        map_b = {m['id']: m for m in markets_b}

        # Simple batching: Process list_a in chunks
        batch_size = 20
        for i in range(0, len(list_a), batch_size):
            batch_a = list_a[i:i+batch_size]
            
            prompt = f"""I have two lists of prediction markets. Your task is to identify which markets from List A represent the EXACT SAME event as markets from List B.

List A:
{json.dumps(batch_a, indent=2)}

List B:
{json.dumps(list_b, indent=2)}

For each match, provide a confidence score from 0.0 to 1.0 indicating how certain you are that they represent the same event.
- 1.0 = Absolutely certain they are the same event
- 0.8-0.9 = Very confident, minor wording differences
- 0.6-0.7 = Likely the same, but some ambiguity
- Below 0.6 = Uncertain or different events

Only return matches where you have reasonable confidence (>= 0.5)."""

            try:
                # Using Responses API with gpt-5-mini
                # Build schema manually to ensure additionalProperties: false
                schema = {
                    "type": "object",
                    "properties": {
                        "matches": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id_a": {"type": "string"},
                                    "id_b": {"type": "string"},
                                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                                },
                                "required": ["id_a", "id_b", "confidence"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["matches"],
                    "additionalProperties": False
                }
                
                response = self.client.responses.create(
                    model="gpt-5-mini",
                    instructions="You are a helpful assistant that matches prediction markets and provides confidence scores.",
                    input=prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "MatchResponse",
                            "schema": schema,
                            "strict": True
                        }
                    }
                )
                
                # Extract the output text from the response
                # The Responses API may return multiple output items (reasoning, message, etc.)
                try:
                    if hasattr(response, 'output') and response.output and len(response.output) > 0:
                        # Find the message output item (skip reasoning items)
                        message_item = None
                        for item in response.output:
                            if hasattr(item, 'type') and item.type == 'message' and hasattr(item, 'content') and item.content:
                                message_item = item
                                break
                        
                        if message_item and len(message_item.content) > 0:
                            output_text = message_item.content[0].text
                            match_data = json.loads(output_text)
                            matches = [Match(**m) for m in match_data.get("matches", [])]
                            
                            # Filter by confidence threshold and add to matched pairs
                            for match in matches:
                                if match.confidence >= min_confidence and match.id_a in map_a and match.id_b in map_b:
                                    matched_pairs.append({
                                        "market_a": map_a[match.id_a],
                                        "market_b": map_b[match.id_b],
                                        "confidence": match.confidence
                                    })
                        else:
                            print(f"No message item found in response output. Output items: {[item.type if hasattr(item, 'type') else 'unknown' for item in response.output]}")
                    else:
                        print(f"Response has no output or empty output.")
                except AttributeError as ae:
                    print(f"Error parsing response structure: {ae}")
                except json.JSONDecodeError as je:
                    print(f"Error parsing JSON from response: {je}")
                
            except Exception as e:
                print(f"Error during LLM market matching batch {i}: {e}")

        return matched_pairs
