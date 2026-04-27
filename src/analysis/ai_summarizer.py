""" 
AI Summarizer using Cerebras API
Provides a brief sentence on trading activities.
"""
import logging
import aiohttp
import json
from datetime import datetime
from typing import Dict, Any, List

class AISummarizer:
    def __init__(self, api_key: str, model: str = "zai-glm-4.7"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.cerebras.ai/v1/chat/completions"
        self.logger = logging.getLogger(__name__)

    async def summarize_activities(self, backtest_results: Dict[str, Any]) -> str:
        """Generate a brief sentence summary of backtest activities"""
        if not self.api_key:
            return "No AI summary available (API key missing)."

        # Prepare summary data for the prompt
        summary_data = {
            "total_trades": backtest_results.get("total_trades", 0),
            "win_rate": f"{backtest_results.get('win_rate', 0) * 100:.2f}%",
            "total_pnl": f"{backtest_results.get('total_pnl', 0):.2f}",
            "max_drawdown": f"{backtest_results.get('max_drawdown', 0) * 100:.2f}%",
            "profit_factor": f"{backtest_results.get('profit_factor', 0):.2f}"
        }

        prompt = (
            f"Results: {summary_data['total_trades']} trades, {summary_data['win_rate']} win rate, "
            f"${summary_data['total_pnl']} PnL, {summary_data['max_drawdown']} drawdown.\n\n"
            "Respond with exactly ONE professional English sentence summarizing this performance. "
            "Output ONLY the sentence, no other text."
        )

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You output only the requested format. No explanations."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 100,
                    "temperature": 0.1
                }

                async with session.post(self.base_url, headers=headers, json=payload, timeout=15) as response:
                    data = await response.json()
                    if response.status == 200:
                        try:
                            message = data['choices'][0]['message']
                            text = message.get('content') or message.get('reasoning') or ""
                            
                            # Extract first English sentence (skip Chinese or reasoning)
                            import re
                            # Find sentences that look like English summaries
                            sentences = re.findall(r'[A-Z][^.!?]*(?:trades?|performance|strategy|results?|profit|loss|PnL|win)[^.!?]*[.!?]', text, re.IGNORECASE)
                            if sentences:
                                return sentences[-1].strip()
                            
                            # Fallback: return first 150 chars if no pattern match
                            clean = text.strip()
                            if clean:
                                return clean[:150] + ("..." if len(clean) > 150 else "")
                            return "Strategy evaluation complete."
                        except (KeyError, IndexError) as e:
                            self.logger.error(f"Unexpected JSON structure from Cerebras: {json.dumps(data)}")
                            return "AI summary structure error."
                    else:
                        self.logger.error(f"Cerebras API error ({response.status}): {json.dumps(data)}")
                        return f"AI summary failed (API {response.status})."
        except Exception as e:
            self.logger.error(f"Error calling AISummarizer: {e}", exc_info=True)
            return "AI summary generation encountered an error."
