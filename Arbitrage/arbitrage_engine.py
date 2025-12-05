from typing import List, Dict, Any

class ArbitrageEngine:
    def __init__(self, fee_adjustment: float = 1.0):
        self.fee_adjustment = fee_adjustment

    def find_opportunities(self, matched_pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        opportunities = []
        
        for pair in matched_pairs:
            market_a = pair['market_a']
            market_b = pair['market_b']
            
            # Check Direction 1: Buy Yes on A, Buy No on B
            cost_1 = market_a['yes_price'] + market_b['no_price']
            profit_1 = self.fee_adjustment - cost_1
            
            if profit_1 > 0:
                opportunities.append({
                    "type": "Arbitrage",
                    "market_a": market_a,
                    "market_b": market_b,
                    "strategy": f"Buy YES on {market_a['platform']} ({market_a['yes_price']}), Buy NO on {market_b['platform']} ({market_b['no_price']})",
                    "cost": cost_1,
                    "profit": profit_1,
                    "roi": (profit_1 / cost_1) * 100 if cost_1 > 0 else 0
                })

            # Check Direction 2: Buy No on A, Buy Yes on B
            cost_2 = market_a['no_price'] + market_b['yes_price']
            profit_2 = self.fee_adjustment - cost_2
            
            if profit_2 > 0:
                opportunities.append({
                    "type": "Arbitrage",
                    "market_a": market_a,
                    "market_b": market_b,
                    "strategy": f"Buy NO on {market_a['platform']} ({market_a['no_price']}), Buy YES on {market_b['platform']} ({market_b['yes_price']})",
                    "cost": cost_2,
                    "profit": profit_2,
                    "roi": (profit_2 / cost_2) * 100 if cost_2 > 0 else 0
                })
                
        return opportunities
