"""
QUICK FIX: Improved Currency Keywords for Better News Matching
===============================================================

This file contains the same refactored news fetching logic, but with BROADENED
currency keywords to improve matching rates. Replace the CURRENCY_KEYWORDS 
in FINNHUB_NEWS_FETCHING_REFACTORED.py with these values.

The original keywords were too strict (only exact currency codes), causing
most news articles to be filtered out. These new keywords are much more lenient.
"""

# UPDATED: More lenient currency keywords for better article matching
UPDATED_CURRENCY_KEYWORDS = {
    "EUR": [
        "eur", "euro", "eurozone", "ecb", "european central bank",
        "draghi", "lagarde", "germany", "france", "italy", "spain",
        "german", "french", "italian", "spanish"
    ],
    "GBP": [
        "gbp", "pound", "sterling", "boe", "bank of england",
        "bailey", "uk", "british", "britain", "england"
    ],
    "JPY": [
        "jpy", "japan", "yen", "boj", "bank of japan",
        "nikkei", "abenomics", "japanese", "tokyo"
    ],
    "CHF": [
        "chf", "swiss", "switzerland", "snb", "swiss national bank",
        "franc", "zurich"
    ],
    "AUD": [
        "aud", "australia", "aussie", "rba", "reserve bank",
        "australian", "sydney", "melbourne"
    ],
    "CAD": [
        "cad", "canada", "canadian", "boc", "bank of canada",
        "loonie", "toronto", "vancouver"
    ],
    "NZD": [
        "nzd", "new zealand", "zealand", "kiwi", "rbnz",
        "reserve bank of new", "auckland", "wellington"
    ],
    "USD": [
        "usd", "dollar", "fed", "federal reserve", "fomc",
        "powell", "jerome", "us dollar", "american"
    ],
}

# HOW TO APPLY THIS FIX:
# ======================
# 1. Open FINNHUB_NEWS_FETCHING_REFACTORED.py
# 2. Find the CURRENCY_KEYWORDS dictionary (around line 44)
# 3. Replace the entire dictionary with UPDATED_CURRENCY_KEYWORDS above
# 4. Save and test
#
# OR run this Python command to update automatically:
# 
# python -c "
# import re
# with open('FINNHUB_NEWS_FETCHING_REFACTORED.py', 'r') as f:
#     content = f.read()
# 
# # Find and replace the keywords
# old_pattern = r'CURRENCY_KEYWORDS = \{[^}]+\}'
# new_keywords = '''CURRENCY_KEYWORDS = {
#     \"EUR\": [\"eur\", \"euro\", \"eurozone\", \"ecb\", \"draghi\", \"lagarde\", \"german\", \"france\", \"italy\"],
#     \"GBP\": [\"gbp\", \"pound\", \"sterling\", \"boe\", \"bailey\", \"uk\", \"british\"],
#     \"JPY\": [\"jpy\", \"japan\", \"yen\", \"boj\", \"nikkei\"],
#     \"CHF\": [\"chf\", \"swiss\", \"snb\"],
#     \"AUD\": [\"aud\", \"australia\", \"aussie\", \"rba\"],
#     \"CAD\": [\"cad\", \"canada\", \"canadian\", \"boc\"],
#     \"NZD\": [\"nzd\", \"zealand\", \"kiwi\", \"rbnz\"],
#     \"USD\": [\"usd\", \"dollar\", \"fed\", \"fomc\", \"powell\"],
# }'''
# 
# content = re.sub(old_pattern, new_keywords, content, flags=re.DOTALL)
# 
# with open('FINNHUB_NEWS_FETCHING_REFACTORED.py', 'w') as f:
#     f.write(content)
# "
